"""
Analytics Router
=================
Dashboard and reporting endpoints. All protected (auth required).

Phase 15 — Redis caching:
  Analytics queries are expensive (aggregate SQL across many rows).
  We cache results in Redis with a 1-hour TTL.
  Cache is invalidated when the user adds/deletes an expense.
  Cache-aside pattern: check Redis first, fall back to DB on miss.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Query

from app.analytics.service import AnalyticsService
from app.cache import cache_delete_pattern, cache_get, cache_set
from app.dependencies import DB, CurrentUser

router = APIRouter()

# Cache TTL: analytics data is cached for 1 hour.
# Users adding an expense see stale dashboard for up to 1h unless we invalidate.
_CACHE_TTL = 3600


def _current_year_month() -> tuple[int, int]:
    now = datetime.now(UTC)
    return now.year, now.month


def _cache_key(user_id: object, endpoint: str, **kwargs: object) -> str:
    """Build a namespaced cache key: analytics:<user_id>:<endpoint>:<params>"""
    params = ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return f"analytics:{user_id}:{endpoint}:{params}"


async def invalidate_analytics_cache(user_id: object) -> None:
    """
    Call this after any write (create/delete expense) to clear stale cache.
    Deletes all analytics keys for this user with one Redis KEYS + DEL call.
    """
    await cache_delete_pattern(f"analytics:{user_id}:*")


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

    key = _cache_key(current_user.id, "summary", year=year, month=month)
    cached = await cache_get(key)
    if cached:
        return json.loads(cached)  # type: ignore[no-any-return]

    svc = AnalyticsService(db)
    result = await svc.get_dashboard_summary(current_user.id, year, month)
    await cache_set(key, json.dumps(result, default=str), _CACHE_TTL)
    return result


@router.get(
    "/trends",
    summary="Monthly expense and income trends",
    description="Expense/income totals grouped by month for the last N months. Used for charts.",
)
async def get_trends(
    current_user: CurrentUser,
    db: DB,
    months: int = Query(default=6, ge=1, le=24),
) -> list[dict]:
    key = _cache_key(current_user.id, "trends", months=months)
    cached = await cache_get(key)
    if cached:
        return json.loads(cached)  # type: ignore[no-any-return]

    svc = AnalyticsService(db)
    result = await svc.get_monthly_trends(current_user.id, months)
    await cache_set(key, json.dumps(result, default=str), _CACHE_TTL)
    return result


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

    key = _cache_key(current_user.id, "category-breakdown", year=year, month=month)
    cached = await cache_get(key)
    if cached:
        return json.loads(cached)  # type: ignore[no-any-return]

    svc = AnalyticsService(db)
    result = await svc.get_category_breakdown(current_user.id, year, month)
    await cache_set(key, json.dumps(result, default=str), _CACHE_TTL)
    return result


@router.get("/top-expenses", summary="Top N largest expenses this month")
async def get_top_expenses(
    current_user: CurrentUser,
    db: DB,
    year: int = Query(default=None),
    month: int = Query(default=None),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[dict]:
    if year is None or month is None:
        year, month = _current_year_month()

    key = _cache_key(
        current_user.id, "top-expenses", year=year, month=month, limit=limit
    )
    cached = await cache_get(key)
    if cached:
        return json.loads(cached)  # type: ignore[no-any-return]

    svc = AnalyticsService(db)
    result = await svc.get_top_expenses(current_user.id, year, month, limit)
    await cache_set(key, json.dumps(result, default=str), _CACHE_TTL)
    return result


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

    key = _cache_key(current_user.id, "budget-vs-actual", year=year, month=month)
    cached = await cache_get(key)
    if cached:
        return json.loads(cached)  # type: ignore[no-any-return]

    svc = AnalyticsService(db)
    result = await svc.get_budget_vs_actual(current_user.id, year, month)
    await cache_set(key, json.dumps(result, default=str), _CACHE_TTL)
    return result
