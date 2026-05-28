"""
Router Aggregator
==================
Combines all module routers into a single router included in main.py.

Pattern: Central router with prefix + tags
  /api/v1/health      → health router
  /api/v1/auth        → auth router
  /api/v1/categories  → category router
  /api/v1/expenses    → expenses router
  /api/v1/calculator  → calculator router (no auth required)
  /api/v1/analytics   → analytics router
  (future)
  /api/v1/income      → income router
  /api/v1/budgets     → budgets router

Why /api/v1/?
  /api: separates API from HTML pages
  /v1: version prefix — add /v2/ for breaking changes while v1 keeps working
"""

from fastapi import APIRouter

from app.analytics.router import router as analytics_router
from app.auth.router import router as auth_router
from app.calculator.router import router as calculator_router
from app.expenses.router import categories_router, expenses_router
from app.health import router as health_router

# Main API router — all routes prefixed with /api/v1
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router, prefix="/health", tags=["Health"])
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(categories_router, prefix="/categories", tags=["Categories"])
api_router.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
api_router.include_router(calculator_router, prefix="/calculator", tags=["Calculator"])
api_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])

# Future routers (uncomment as each phase is built):
# from app.income.router import router as income_router
# from app.budgets.router import router as budgets_router
# api_router.include_router(income_router,  prefix="/income",  tags=["Income"])
# api_router.include_router(budgets_router, prefix="/budgets", tags=["Budgets"])
