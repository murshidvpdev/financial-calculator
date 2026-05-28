"""
Database Configuration — SQLAlchemy 2.0 Async
===============================================
Sets up the async database engine, session factory, and base model.

Why SQLAlchemy 2.0?
  - Full async support (no blocking I/O during DB queries)
  - New "2.0 style" API (cleaner, more Pythonic)
  - Better type hints and IDE support
  - Same power as SQLAlchemy 1.x with modern patterns

SQLAlchemy Architecture:
  Engine       → Low-level: manages the connection pool, speaks SQL
  Session      → High-level: Unit of Work pattern, tracks changes to objects
  Base Model   → Your Python classes that map to database tables

Connection Pool:
  Instead of opening a new database connection for every request (expensive!),
  SQLAlchemy maintains a POOL of connections that are reused.

  pool_size=10 → Keep 10 connections open always
  max_overflow=20 → Allow up to 30 total (10 + 20 extra when busy)
  pool_timeout=30 → Wait up to 30s for an available connection

  Analogy: Like a taxi fleet. pool_size = taxis always on duty.
           max_overflow = extra taxis called during rush hour.
           pool_timeout = how long to wait if ALL taxis are busy.

Interview: "We use SQLAlchemy 2.0 with asyncpg for async PostgreSQL access.
The async engine means database I/O doesn't block the event loop.
We use a session-per-request pattern via FastAPI dependency injection."
"""

import time
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# =============================================================================
# ENGINE — The database connection manager
# =============================================================================
# Module-level variable: initialized during startup, reused for all requests
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine() -> AsyncEngine:
    """
    Create the async SQLAlchemy engine.

    echo=True in development → logs all SQL queries (helpful for learning!)
    echo=False in production → no SQL logging (performance + security)
    """
    return create_async_engine(
        settings.database_url,
        # Log all SQL in development (great for learning SQLAlchemy)
        echo=settings.debug,
        # Connection pool settings
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        # Close connections that have been idle for 10 minutes
        # (prevents "connection closed by server" errors on long-idle apps)
        pool_recycle=600,
        # Verify connections before using them (catches stale connections)
        pool_pre_ping=True,
        # Connection arguments for asyncpg
        connect_args={
            "command_timeout": 60,  # Cancel query if it takes >60 seconds
            "server_settings": {
                "application_name": settings.app_name,  # Visible in pg_stat_activity
            },
        },
    )


async def init_db() -> None:
    """
    Initialize the database engine and session factory.
    Called once during application startup (in lifespan).
    """
    global _engine, _session_factory

    # Import ALL models here to ensure SQLAlchemy mapper initializes correctly.
    # SQLAlchemy needs ALL models imported before the first session/query,
    # because relationship strings ("Expense", "User") are resolved at mapper
    # initialization time. Without this import, you get:
    #   "expression 'Expense' failed to locate a name"
    # This is the standard solution for modular SQLAlchemy applications.
    import app.expenses.models  # noqa: F401
    import app.users.models  # noqa: F401

    _engine = _create_engine()

    # Session factory: creates new AsyncSession objects on demand
    # expire_on_commit=False: don't expire ORM objects after commit
    # (important for async: avoids lazy-loading issues)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    logger.info("database_engine_initialized", pool_size=settings.database_pool_size)

    # Seed default categories (idempotent — skips if already seeded)
    from app.expenses.service import seed_default_categories

    async with _session_factory() as session:
        await seed_default_categories(session)


async def close_db() -> None:
    """
    Close the database engine and all connections.
    Called during application shutdown.
    """
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("database_engine_disposed")


async def check_db_connection() -> float:
    """
    Check database connectivity and return query latency in milliseconds.
    Used by health check endpoints.
    """
    if not _engine:
        raise RuntimeError("Database engine not initialized")

    start = time.perf_counter()
    async with _engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return latency_ms


async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    FastAPI dependency that provides a database session per request.

    Pattern: Session-per-request
      - A new session is created for each HTTP request
      - The session is committed on success
      - The session is rolled back on any exception
      - The session is always closed at the end

    Usage in FastAPI endpoints:
        from app.database import get_db
        from sqlalchemy.ext.asyncio import AsyncSession

        @router.get("/expenses")
        async def list_expenses(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Expense))
            return result.scalars().all()

    This is the Dependency Injection pattern — FastAPI calls get_db(),
    gives the session to your handler, then runs the cleanup code.
    """
    if not _session_factory:
        raise RuntimeError("Database not initialized. Was init_db() called?")

    async with _session_factory() as session:
        try:
            yield session  # ← Give the session to the handler
            await session.commit()  # ← Commit on success
        except Exception:
            await session.rollback()  # ← Rollback on any exception
            raise
        finally:
            await session.close()  # ← Always close (return to pool)


# =============================================================================
# BASE MODEL — All database models inherit from this
# =============================================================================
class Base(DeclarativeBase):
    """
    SQLAlchemy Declarative Base.

    All our database models inherit from this class.
    It provides:
    - Registry of all models (SQLAlchemy knows about all tables)
    - metadata object (used by Alembic for migrations)

    Usage:
        class User(Base):
            __tablename__ = "users"
            id = mapped_column(UUID, primary_key=True)
            ...
    """

    pass
