"""
Finance Calculator — FastAPI Application Entry Point
====================================================
This is the main application file. It:
1. Creates the FastAPI application instance
2. Configures the lifespan (startup + shutdown)
3. Registers all middleware (request ID, timing, security, CORS)
4. Registers all exception handlers (404, 422, 500, etc.)
5. Includes all routers (auth, expenses, budgets, analytics, etc.)
6. Sets up static files and templates

Architecture:
  main.py is intentionally THIN — it just wires things together.
  Business logic lives in service classes, not here.
  This separation makes testing easier (test services independently).

Running the app:
  Development: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  Production:  uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8000
               (or via gunicorn: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker)
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.core.logging import setup_logging
from app.core.middleware import (
    RequestIDMiddleware,
    RequestTimingMiddleware,
    SecurityHeadersMiddleware,
)
from app.exceptions import (
    FinanceAppError,
    finance_app_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.pages.router import router as pages_router
from app.routers import api_router

# Get logger for this module
logger = structlog.get_logger(__name__)

settings = get_settings()


# =============================================================================
# LIFESPAN — Application Startup and Shutdown
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Application lifespan manager.

    Code BEFORE yield runs on startup.
    Code AFTER yield runs on shutdown.

    This replaces the old @app.on_event("startup") / @app.on_event("shutdown")
    decorators — the new way (Python 3.10+) using contextmanager is cleaner.

    Why use a context manager?
      It guarantees cleanup even if startup partially fails.
      Like a try/finally block for the entire application.
    """
    # -------------------------------------------------------------------------
    # STARTUP
    # -------------------------------------------------------------------------
    # 1. Configure logging first (so startup messages are properly logged)
    setup_logging()
    logger.info(
        "application_starting",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.env,
        debug=settings.debug,
    )

    # 2. Connect to the database
    from app.database import close_db, init_db

    await init_db()
    logger.info(
        "database_connected", url=settings.database_url.split("@")[-1]
    )  # Don't log credentials

    # 3. Connect to Redis (gracefully — Redis is optional in dev)
    try:
        from app.cache import close_redis, init_redis

        await init_redis()
        logger.info("redis_connected")
    except Exception as e:
        # Redis is not critical for startup — app works without it
        # But rate limiting and sessions will be degraded
        logger.warning("redis_connection_failed", error=str(e))

    logger.info(
        "application_ready",
        host=settings.host,
        port=settings.port,
        docs_url=(
            f"http://localhost:{settings.port}/docs"
            if settings.docs_url
            else "disabled"
        ),
    )

    # -------------------------------------------------------------------------
    # YIELD — Application runs here (handles all requests)
    # -------------------------------------------------------------------------
    yield

    # -------------------------------------------------------------------------
    # SHUTDOWN — Everything after yield runs when the app is stopping
    # -------------------------------------------------------------------------
    logger.info("application_shutting_down")

    # Close Redis connection pool
    try:
        await close_redis()
        logger.info("redis_disconnected")
    except Exception as e:
        logger.warning("redis_close_failed", error=str(e))

    # Close database connection pool
    await close_db()
    logger.info("database_disconnected")

    logger.info("application_stopped")


# =============================================================================
# FASTAPI APPLICATION INSTANCE
# =============================================================================
def create_application() -> FastAPI:
    """
    Application factory function.

    Why use a factory instead of module-level app = FastAPI()?
    - Easier to test: call create_application() with different settings in tests
    - Cleaner: all setup is explicit and in one place
    - Reusable: create multiple apps with different configs if needed

    This is the Factory Pattern applied to FastAPI.
    """

    app = FastAPI(
        title=settings.app_name,
        description="""
## Finance Calculator & Expense Tracker

A production-grade personal finance API with:
- 💸 **Expense tracking** — daily, monthly, yearly
- 💰 **Income tracking** with categorization
- 📊 **Budget management** with alerts
- 📈 **Analytics dashboard** with trends
- 🧮 **Finance calculators** (EMI, compound interest, SIP)
- 🎯 **Savings goals** tracking
- 🔐 **JWT authentication** with RBAC

Built with FastAPI + PostgreSQL + Redis.
        """,
        version=settings.app_version,
        # Only expose docs in development (security: don't expose API schema in prod)
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url="/openapi.json" if settings.is_development else None,
        # Lifespan replaces on_event startup/shutdown
        lifespan=lifespan,
    )

    # -------------------------------------------------------------------------
    # MIDDLEWARE (order matters — added in REVERSE order of execution)
    # First added = outermost = runs first on request, last on response
    # -------------------------------------------------------------------------

    # 1. CORS — Must be first (outermost) to handle preflight requests
    #    Cross-Origin Resource Sharing: allows JavaScript on other domains
    #    to call our API. Required if you ever add a React frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )

    # 2. Security headers — add security headers to all responses
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. Request timing — measure and log request duration
    app.add_middleware(RequestTimingMiddleware)

    # 4. Request ID — assign unique ID to every request (innermost, runs first)
    app.add_middleware(RequestIDMiddleware)

    # -------------------------------------------------------------------------
    # EXCEPTION HANDLERS
    # -------------------------------------------------------------------------
    # Register handlers for different exception types
    # FastAPI matches the most specific exception type first

    # Our custom domain exceptions
    app.add_exception_handler(FinanceAppError, finance_app_exception_handler)  # type: ignore[arg-type]

    # FastAPI's built-in HTTP exceptions (404, 405, etc.)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]

    # Pydantic validation errors (malformed request bodies)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]

    # Catch-all for any unhandled exceptions
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

    # -------------------------------------------------------------------------
    # ROUTERS — Include all API route modules
    # -------------------------------------------------------------------------
    app.include_router(api_router)

    # HTML page routes (/, /login, /dashboard, /expenses)
    app.include_router(pages_router)

    # -------------------------------------------------------------------------
    # STATIC FILES & TEMPLATES
    # -------------------------------------------------------------------------
    # Serve static files (CSS, JS, images) from /static path
    app.mount("/static", StaticFiles(directory="static"), name="static")

    return app


# =============================================================================
# APPLICATION INSTANCE
# =============================================================================
# This is what uvicorn imports: uvicorn app.main:app
app = create_application()
