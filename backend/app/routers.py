"""
Router Aggregator
==================
Combines all module routers into a single router that's included in main.py.

Why this file?
  Instead of adding 10 routers in main.py, we add ONE router here.
  This keeps main.py clean and makes it easy to see all API routes in one place.

Pattern: Central router with prefix + tags
  /api/v1/health     → health router
  /api/v1/auth       → auth router
  /api/v1/expenses   → expenses router
  /api/v1/budgets    → budgets router
  etc.

Why /api/v1/?
  - /api: clearly separates API from HTML pages (we serve both)
  - /v1: version prefix enables non-breaking changes in the future
          When you need breaking changes, add /v2/ routes while v1 still works
"""

from fastapi import APIRouter

from app.health import router as health_router

# Main API router -- all routes are prefixed with /api/v1
api_router = APIRouter(prefix="/api/v1")

# Include sub-routers
api_router.include_router(health_router, prefix="/health", tags=["Health"])

# Future routers (uncommented as we build each phase):
# from app.auth.router import router as auth_router
# from app.users.router import router as users_router
# from app.expenses.router import router as expenses_router
# from app.income.router import router as income_router
# from app.budgets.router import router as budgets_router
# from app.analytics.router import router as analytics_router
# from app.calculator.router import router as calculator_router

# api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
# api_router.include_router(users_router, prefix="/users", tags=["Users"])
# api_router.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
# api_router.include_router(income_router, prefix="/income", tags=["Income"])
# api_router.include_router(budgets_router, prefix="/budgets", tags=["Budgets"])
# api_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
# api_router.include_router(calculator_router, prefix="/calculator", tags=["Calculator"])
