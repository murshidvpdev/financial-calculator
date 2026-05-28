"""
Analytics Router
=================
Dashboard and reporting endpoints. All protected (auth required).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from app.analytics.service import AnalyticsService
from app.dependencies import DB, CurrentUser

router = APIRouter()


def _current_year_month() -> tuple[int, int]:
    now = datetime.now(UTC)
    return now.year, now.month


@router.get(
    "/summary",
    summary="Dashboard summary for a given month",
    description="Total income, expenses, savings, savings rate, and MoM comparison.",
)
async def get_summary(
    current_user: CurrentUser,
    db: DB,
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
) -> dict:
    if year is None or month is None:
        year, month = _current_year_month()
    svc = AnalyticsService(db)
    return await svc.get_dashboard_summary(current_user.id, year, month)


@router.get(
    "/trends",
    summary="Monthly expense and income trends",
    description="Expense/income totals grouped by month for the last N months. Used for charts.",
)
async def get_trends(
    current_user: CurrentUser,
    db: DB,
    months: int = Query(
        default=6, ge=1, le=24, description="How many months back to show"
    ),
) -> list[dict]:
    svc = AnalyticsService(db)
    return await svc.get_monthly_trends(current_user.id, months)


@router.get(
    "/category-breakdown",
    summary="Expense breakdown by category",
    description="Expenses grouped by category with amounts and percentages. Used for pie charts.",
)
async def get_category_breakdown(
    current_user: CurrentUser,
    db: DB,
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
) -> list[dict]:
    if year is None or month is None:
        year, month = _current_year_month()
    svc = AnalyticsService(db)
    return await svc.get_category_breakdown(current_user.id, year, month)


@router.get(
    "/top-expenses",
    summary="Top N largest expenses this month",
)
async def get_top_expenses(
    current_user: CurrentUser,
    db: DB,
    year: int = Query(default=None),
    month: int = Query(default=None),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[dict]:
    if year is None or month is None:
        year, month = _current_year_month()
    svc = AnalyticsService(db)
    return await svc.get_top_expenses(current_user.id, year, month, limit)


@router.get(
    "/budget-vs-actual",
    summary="Budget vs actual spending by category",
    description="Compare your budgets against real spending. Shows on-track / warning / over-budget status.",
)
async def get_budget_vs_actual(
    current_user: CurrentUser,
    db: DB,
    year: int = Query(default=None),
    month: int = Query(default=None),
) -> list[dict]:
    if year is None or month is None:
        year, month = _current_year_month()
    svc = AnalyticsService(db)
    return await svc.get_budget_vs_actual(current_user.id, year, month)
