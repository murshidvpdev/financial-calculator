"""
Analytics Service
==================
SQL aggregation queries for the dashboard and reports.

Key SQL patterns used here:

  1. SUM / COUNT / AVG — basic aggregations
  2. GROUP BY — group expenses by month, by category
  3. DATE_TRUNC — truncate timestamps to month/year (PostgreSQL function)
  4. Window functions — running totals, month-over-month change
  5. Subqueries — budget vs actual comparison
  6. COALESCE — replace NULL with 0 in aggregations

Why analytics lives in its own service:
  - These queries are READ-ONLY (no mutations)
  - They join multiple tables in complex ways
  - Performance matters — analytics queries can be slow on large datasets
  - In future: analytics can hit a read-replica while mutations go to primary

Interview: "Analytics queries are kept in a separate service and run
against read replicas in production. We use DATE_TRUNC to group by month,
GROUP BY for category breakdowns, and window functions for trend analysis.
COALESCE(SUM(amount), 0) prevents NULL results when no data exists."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.expenses.models import Budget, Category, Expense, Income

logger = structlog.get_logger(__name__)


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────────
    # DASHBOARD SUMMARY
    # ──────────────────────────────────────────────────────────────────────────

    async def get_dashboard_summary(
        self,
        user_id: uuid.UUID,
        year: int,
        month: int,
    ) -> dict:
        """
        High-level numbers for the dashboard header cards:
          - Total income this month
          - Total expenses this month
          - Net savings (income - expenses)
          - Savings rate (savings / income × 100)
          - Expense count
          - vs last month (month-over-month change)

        SQL strategy: two separate queries (income + expense) then combine in Python.
        Could be one query with conditional aggregation but two queries are clearer.
        """
        # Build date range for the requested month
        from_dt = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            to_dt = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            to_dt = datetime(year, month + 1, 1, tzinfo=UTC)

        # Previous month for MoM comparison
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_from = datetime(prev_year, prev_month, 1, tzinfo=UTC)
        prev_to = from_dt

        async def _sum_expenses(start: datetime, end: datetime) -> dict:
            result = await self.db.execute(
                select(
                    func.coalesce(func.sum(Expense.amount), 0).label("total"),
                    func.count(Expense.id).label("count"),
                ).where(
                    Expense.user_id == user_id,
                    Expense.deleted_at.is_(None),
                    Expense.date >= start,
                    Expense.date < end,
                )
            )
            row = result.one()
            return {"total": Decimal(str(row.total)), "count": int(row.count)}  # type: ignore[call-overload]

        async def _sum_income(start: datetime, end: datetime) -> Decimal:
            result = await self.db.execute(
                select(func.coalesce(func.sum(Income.amount), 0).label("total")).where(
                    Income.user_id == user_id,
                    Income.deleted_at.is_(None),
                    Income.date >= start,
                    Income.date < end,
                )
            )
            return Decimal(str(result.scalar_one()))

        # Current month
        curr_exp = await _sum_expenses(from_dt, to_dt)
        curr_income = await _sum_income(from_dt, to_dt)

        # Previous month
        prev_exp = await _sum_expenses(prev_from, prev_to)
        prev_income = await _sum_income(prev_from, prev_to)

        total_expenses = curr_exp["total"]
        total_income = curr_income
        net_savings = total_income - total_expenses
        savings_rate = (
            (net_savings / total_income * 100) if total_income > 0 else Decimal("0")
        )

        def _pct_change(curr: Decimal, prev: Decimal) -> Decimal:
            if prev == 0:
                return Decimal("100") if curr > 0 else Decimal("0")
            return ((curr - prev) / prev * 100).quantize(Decimal("0.01"))

        return {
            "period": {"year": year, "month": month},
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_savings": net_savings,
            "savings_rate_pct": savings_rate.quantize(Decimal("0.01")),
            "expense_count": curr_exp["count"],
            "vs_last_month": {
                "expense_change_pct": _pct_change(total_expenses, prev_exp["total"]),
                "income_change_pct": _pct_change(total_income, prev_income),
                "prev_expenses": prev_exp["total"],
                "prev_income": prev_income,
            },
        }

    # ──────────────────────────────────────────────────────────────────────────
    # MONTHLY TRENDS  (last N months)
    # ──────────────────────────────────────────────────────────────────────────

    async def get_monthly_trends(
        self,
        user_id: uuid.UUID,
        months: int = 6,
    ) -> list[dict]:
        """
        Expense and income totals grouped by month for the last N months.
        Used for line/bar charts on the dashboard.

        SQL:
          SELECT
            DATE_TRUNC('month', date) AS month,
            SUM(amount) AS total,
            COUNT(*) AS count
          FROM expenses
          WHERE user_id = :uid AND deleted_at IS NULL
            AND date >= NOW() - INTERVAL ':months months'
          GROUP BY month
          ORDER BY month ASC

        DATE_TRUNC('month', '2026-05-15') → '2026-05-01 00:00:00'
        This groups all dates in May into the same bucket.
        """
        since = datetime.now(UTC) - timedelta(days=months * 31)

        # Expense trend
        exp_result = await self.db.execute(
            select(
                func.date_trunc("month", Expense.date).label("month"),
                func.sum(Expense.amount).label("total"),
                func.count(Expense.id).label("count"),
            )
            .where(
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
                Expense.date >= since,
            )
            .group_by(text("month"))
            .order_by(text("month ASC"))
        )
        exp_rows = exp_result.all()

        # Income trend
        inc_result = await self.db.execute(
            select(
                func.date_trunc("month", Income.date).label("month"),
                func.sum(Income.amount).label("total"),
            )
            .where(
                Income.user_id == user_id,
                Income.deleted_at.is_(None),
                Income.date >= since,
            )
            .group_by(text("month"))
            .order_by(text("month ASC"))
        )
        inc_rows = {row.month: Decimal(str(row.total)) for row in inc_result.all()}

        return [
            {
                "month": row.month.strftime("%Y-%m"),
                "month_label": row.month.strftime("%b %Y"),
                "total_expenses": Decimal(str(row.total)),
                "expense_count": int(row.count),  # type: ignore[call-overload]
                "total_income": inc_rows.get(row.month, Decimal("0")),
                "net": inc_rows.get(row.month, Decimal("0")) - Decimal(str(row.total)),
            }
            for row in exp_rows
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # CATEGORY BREAKDOWN
    # ──────────────────────────────────────────────────────────────────────────

    async def get_category_breakdown(
        self,
        user_id: uuid.UUID,
        year: int,
        month: int,
    ) -> list[dict]:
        """
        Expenses grouped by category for a given month.
        Used for pie/donut charts.

        SQL:
          SELECT
            c.name, c.color, c.icon,
            SUM(e.amount) AS total,
            COUNT(e.id) AS count,
            SUM(e.amount) / total_month_expenses * 100 AS percentage
          FROM expenses e
          LEFT JOIN categories c ON e.category_id = c.id
          WHERE e.user_id = :uid AND ...
          GROUP BY c.id, c.name, c.color, c.icon
          ORDER BY total DESC
        """
        from_dt = datetime(year, month, 1, tzinfo=UTC)
        to_dt = (
            datetime(year, month + 1, 1, tzinfo=UTC)
            if month < 12
            else datetime(year + 1, 1, 1, tzinfo=UTC)
        )

        result = await self.db.execute(
            select(
                Category.id.label("category_id"),
                Category.name.label("category_name"),
                Category.color.label("color"),
                Category.icon.label("icon"),
                func.sum(Expense.amount).label("total"),
                func.count(Expense.id).label("count"),
            )
            .outerjoin(Category, Expense.category_id == Category.id)
            .where(
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
                Expense.date >= from_dt,
                Expense.date < to_dt,
            )
            .group_by(Category.id, Category.name, Category.color, Category.icon)
            .order_by(text("total DESC"))
        )
        rows = result.all()

        grand_total = sum(Decimal(str(r.total)) for r in rows) or Decimal("1")

        return [
            {
                "category_id": str(row.category_id) if row.category_id else None,
                "category_name": row.category_name or "Uncategorized",
                "color": row.color or "#CCD1D1",
                "icon": row.icon or "📦",
                "total": Decimal(str(row.total)),
                "count": int(row.count),  # type: ignore[call-overload]
                "percentage": (Decimal(str(row.total)) / grand_total * 100).quantize(
                    Decimal("0.01")
                ),
            }
            for row in rows
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # TOP EXPENSES
    # ──────────────────────────────────────────────────────────────────────────

    async def get_top_expenses(
        self,
        user_id: uuid.UUID,
        year: int,
        month: int,
        limit: int = 5,
    ) -> list[dict]:
        """Top N largest expenses for the month — quick spending insight."""
        from_dt = datetime(year, month, 1, tzinfo=UTC)
        to_dt = (
            datetime(year, month + 1, 1, tzinfo=UTC)
            if month < 12
            else datetime(year + 1, 1, 1, tzinfo=UTC)
        )

        result = await self.db.execute(
            select(
                Expense.id,
                Expense.description,
                Expense.amount,
                Expense.date,
                Category.name.label("category_name"),
                Category.icon.label("category_icon"),
            )
            .outerjoin(Category, Expense.category_id == Category.id)
            .where(
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
                Expense.date >= from_dt,
                Expense.date < to_dt,
            )
            .order_by(Expense.amount.desc())
            .limit(limit)
        )

        return [
            {
                "id": str(row.id),
                "description": row.description,
                "amount": Decimal(str(row.amount)),
                "date": row.date.isoformat(),
                "category": row.category_name or "Uncategorized",
                "category_icon": row.category_icon or "📦",
            }
            for row in result.all()
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # BUDGET vs ACTUAL
    # ──────────────────────────────────────────────────────────────────────────

    async def get_budget_vs_actual(
        self,
        user_id: uuid.UUID,
        year: int,
        month: int,
    ) -> list[dict]:
        """
        Compare budgeted amounts against actual spending per category.

        SQL: LEFT JOIN budgets ON category for the period, then
             subquery actual spending per category.

        Returns progress percentage: actual / budget × 100
        Red flag: > 100% (over budget)
        Warning:  > 80% (approaching limit)
        """
        from_dt = datetime(year, month, 1, tzinfo=UTC)
        to_dt = (
            datetime(year, month + 1, 1, tzinfo=UTC)
            if month < 12
            else datetime(year + 1, 1, 1, tzinfo=UTC)
        )

        # Actual spending per category this month
        actual_result = await self.db.execute(
            select(
                Expense.category_id,
                func.sum(Expense.amount).label("actual"),
            )
            .where(
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
                Expense.date >= from_dt,
                Expense.date < to_dt,
            )
            .group_by(Expense.category_id)
        )
        actuals = {
            row.category_id: Decimal(str(row.actual)) for row in actual_result.all()
        }

        # Budgets for this month
        budget_result = await self.db.execute(
            select(
                Budget.category_id,
                Budget.amount,
                Category.name,
                Category.color,
                Category.icon,
            )
            .outerjoin(Category, Budget.category_id == Category.id)
            .where(
                Budget.user_id == user_id,
                Budget.is_active.is_(True),
                Budget.period_start <= from_dt,
                Budget.period_end >= from_dt,
            )
        )
        rows = budget_result.all()

        result = []
        for row in rows:
            budget_amt = Decimal(str(row.amount))
            actual_amt = actuals.get(row.category_id, Decimal("0"))
            pct_used = (
                (actual_amt / budget_amt * 100) if budget_amt > 0 else Decimal("0")
            )
            result.append(
                {
                    "category_id": str(row.category_id) if row.category_id else None,
                    "category_name": row.name or "Overall",
                    "color": row.color or "#CCD1D1",
                    "icon": row.icon or "📦",
                    "budget": budget_amt,
                    "actual": actual_amt,
                    "remaining": budget_amt - actual_amt,
                    "pct_used": pct_used.quantize(Decimal("0.01")),
                    "status": (
                        "over_budget"
                        if pct_used > 100
                        else "warning"
                        if pct_used > 80
                        else "on_track"
                    ),
                }
            )

        return sorted(result, key=lambda x: x["pct_used"], reverse=True)
