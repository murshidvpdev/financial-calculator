"""
Alembic Migration Environment
===============================
This file configures how Alembic connects to the database and
discovers your SQLAlchemy models.

Key concepts:
  - autogenerate: Alembic compares your models to the actual DB schema
    and generates migration code automatically. This is the killer feature!
  - online vs offline mode:
    - online: Connects to real DB, applies migrations directly
    - offline: Generates SQL file you apply manually (useful for DBAs in production)

How autogenerate works:
  1. Alembic connects to the database
  2. Reads the current schema (what tables/columns actually exist)
  3. Compares to your SQLAlchemy models (what SHOULD exist)
  4. Generates Python code to make DB match your models

What autogenerate CAN detect:
  - Table additions/removals
  - Column additions/removals
  - Column type changes
  - Index additions/removals
  - Unique constraint changes

What autogenerate CANNOT detect (you must write manually):
  - Data migrations (moving data from one column to another)
  - Stored procedures, triggers
  - Partial index conditions
  - Complex constraints
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# -------------------------------------------------------------------------
# Import ALL models so Alembic knows about them
# CRITICAL: If a model is not imported here, Alembic won't detect it!
# -------------------------------------------------------------------------
from app.database import Base  # noqa: F401 (import for side effects)
from app.expenses.models import Budget, Category, Expense, Income  # noqa: F401
from app.users.models import User, UserProfile  # noqa: F401

# -------------------------------------------------------------------------
# Alembic Config
# -------------------------------------------------------------------------
# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The SQLAlchemy metadata object from our Base model
# Alembic uses this to detect schema changes
target_metadata = Base.metadata


def get_url() -> str:
    """
    Get database URL for migrations.

    Priority:
    1. Environment variable (for CI/CD and production)
    2. alembic.ini file (fallback for local development)

    This allows CI/CD to pass the production DB URL via env var
    without hardcoding it in config files.
    """
    import os

    from dotenv import load_dotenv

    load_dotenv("../.env")
    return os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://finance_user@localhost:5432/finance_db"
    )


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL statements to a file WITHOUT connecting to the database.
    Useful when:
    - A DBA needs to review SQL before applying to production
    - You don't have direct DB access (highly restricted environments)

    Usage: alembic upgrade head --sql > migration.sql
    Then: psql production_db < migration.sql
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include these for complete schema comparison
        compare_type=True,  # Detect column type changes
        compare_server_default=True,  # Detect default value changes
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure and run migrations with an active DB connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode with async engine.

    FastAPI uses async SQLAlchemy (asyncpg driver).
    Alembic needs to use the same async engine.

    Note: Alembic runs synchronously internally (sync I/O),
    but we use run_sync() to call sync Alembic code from async context.
    """
    # Build async engine using same config as the application
    configuration: dict[str, Any] = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pool for migrations (single-use connection)
    )

    async with connectable.connect() as connection:
        # run_sync: run synchronous Alembic code within async context
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations online (connects to actual database)."""
    asyncio.run(run_async_migrations())


# -------------------------------------------------------------------------
# Choose mode: offline vs online
# -------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
