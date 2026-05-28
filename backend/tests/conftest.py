"""
Test Configuration — Fixtures and Test Database Setup
======================================================

Event Loop Strategy:
  pytest-asyncio gives each async test function its OWN event loop (function scope).
  asyncpg connections are tied to the event loop that created them.

  The critical rule: the SQLAlchemy engine (which owns asyncpg connections)
  MUST be created in the SAME event loop as the test that uses it.

Our approach:
  1. create_test_tables: SYNCHRONOUS fixture (uses asyncio.run() in isolation)
     → Creates/drops schema. Fully isolated, no loop sharing.
  2. client: function-scoped async fixture
     → Calls init_db() which creates the engine IN the test's event loop
     → Calls close_db() after the test to properly dispose the engine
     → Each test gets a fresh engine ← no cross-loop contamination

Test isolation:
  Tests use UUIDs to avoid collisions.
  No rollback pattern — data persists within a session but unique data prevents conflicts.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

# =============================================================================
# Set test database URL BEFORE importing any app code.
# pydantic-settings reads env vars at import time.
# =============================================================================
_TEST_DB_URL = "postgresql+asyncpg://finance_user@localhost:5432/finance_test_db"
os.environ["DATABASE_URL"] = _TEST_DB_URL

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.expenses.models  # noqa: F401

# Import ALL models so SQLAlchemy registers their tables with Base.metadata.
# Without this, create_all skips tables that haven't been imported yet.
import app.users.models  # noqa: F401
from app.database import Base

# =============================================================================
# TABLE CREATION — Synchronous, runs in its own isolated event loop
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    """
    Create all tables before the test session; drop them after.

    Why synchronous (not async)?
      This fixture runs ONCE for the whole session, before any test
      event loops are created. Using asyncio.run() gives it a completely
      isolated event loop that is closed and cleaned up before tests start.

      If we used an async session-scoped fixture, it would share the session
      event loop, and asyncpg connections created here would conflict with
      the function-scoped event loops used by individual tests.
    """

    async def _setup():
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_TEST_DB_URL, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()  # ← dispose BEFORE the loop closes

    async def _teardown():
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_TEST_DB_URL, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_setup())  # Isolated loop → creates tables → loop closes
    yield  # Tests run here
    asyncio.run(_teardown())  # Isolated loop → drops tables → loop closes


# =============================================================================
# HTTP CLIENT — One per test function
# =============================================================================


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """
    Async HTTP client that talks to the FastAPI app via ASGI (no TCP sockets).

    init_db() runs HERE (inside the test's function event loop) so that
    asyncpg creates connections in the same loop the test will use.

    close_db() runs AFTER the test to dispose the engine before the
    function event loop closes — prevents "Future attached to different loop".
    """
    from app.database import close_db, init_db
    from app.main import app

    await init_db()  # Creates engine in THIS test's event loop

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    await close_db()  # Dispose engine BEFORE this event loop closes


# =============================================================================
# USER FIXTURES
# =============================================================================


@pytest_asyncio.fixture
async def test_user(client: AsyncClient) -> dict:
    """
    Register a user via the API and return their credentials.

    Each call creates a unique user (random suffix) so tests don't clash.
    """
    unique_id = str(uuid.uuid4())[:8]
    email = f"test_{unique_id}@example.com"
    username = f"testuser_{unique_id}"
    password = "TestPass123!"

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "username": username,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert resp.status_code == 201, f"User registration failed: {resp.text}"

    data = resp.json()["user"]
    data["password"] = password
    return data


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: dict) -> dict:
    """
    Return Authorization headers with a valid JWT for test_user.

    Example usage:
        resp = await client.get("/api/v1/expenses", headers=auth_headers)
    """
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# CATEGORY AND EXPENSE FIXTURES
# =============================================================================


@pytest_asyncio.fixture
async def test_category(client: AsyncClient, auth_headers: dict) -> dict:
    """Create a test category via the API and return its data."""
    resp = await client.post(
        "/api/v1/categories",
        headers=auth_headers,
        json={
            "name": f"Test Category {uuid.uuid4().hex[:6]}",
            "icon": "🧪",
            "color": "#FF5733",
            "category_type": "expense",
        },
    )
    assert resp.status_code == 201, f"Category creation failed: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture
async def test_expense(
    client: AsyncClient, auth_headers: dict, test_category: dict
) -> dict:
    """Create a test expense via the API and return its data."""
    resp = await client.post(
        "/api/v1/expenses",
        headers=auth_headers,
        json={
            "amount": "49.99",
            "description": "Test expense",
            "category_id": test_category["id"],
            "tags": ["test"],
            "notes": "Test notes",
        },
    )
    assert resp.status_code == 201, f"Expense creation failed: {resp.text}"
    return resp.json()
