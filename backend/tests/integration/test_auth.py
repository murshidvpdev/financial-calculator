"""
Integration Tests — Authentication API
=========================================

Integration tests hit the real HTTP endpoints (via ASGI transport).
They test the full request-response cycle:
  Request → Middleware → Router → Service → Database → Response

What we test:
  - POST /api/v1/auth/register
  - POST /api/v1/auth/login
  - GET  /api/v1/users/me
  - POST /api/v1/auth/logout

Why integration tests vs unit tests?
  Unit tests verify individual functions in isolation.
  Integration tests verify that all the pieces work together:
  validation → service → database → serialization.

  A bug that only appears when Pydantic schema + SQLAlchemy model
  interact would be missed by unit tests but caught here.

Fixtures (from conftest.py):
  client — async HTTP client with dependency injection
  test_user — pre-created user in test DB
  auth_headers — {"Authorization": "Bearer <token>"}
"""

from __future__ import annotations

from httpx import AsyncClient

# =============================================================================
# REGISTRATION TESTS
# =============================================================================


class TestRegister:
    """Tests for POST /api/v1/auth/register."""

    async def test_register_success(self, client: AsyncClient):
        """User can register with valid data."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "username": "newuser",
                "password": "SecurePass123!",
                "first_name": "New",
                "last_name": "User",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["message"] == "Registration successful!"
        assert "user" in data
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["username"] == "newuser"
        assert "hashed_password" not in data["user"]  # Never expose password hash

    async def test_register_returns_uuid_id(self, client: AsyncClient):
        """Registered user response includes a UUID id field."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "uuid_test@example.com",
                "username": "uuid_test",
                "password": "SecurePass123!",
            },
        )
        assert resp.status_code == 201
        user_id = resp.json()["user"]["id"]
        # UUID format: 8-4-4-4-12 hex chars
        import uuid

        uuid.UUID(user_id)  # Raises ValueError if not a valid UUID

    async def test_register_duplicate_email_fails(self, client: AsyncClient, test_user):
        """Registration with an existing email returns 409 Conflict."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": test_user["email"],  # Already exists
                "username": "differentusername",
                "password": "SecurePass123!",
            },
        )
        assert resp.status_code == 409
        assert "already" in resp.json()["message"].lower()

    async def test_register_duplicate_username_fails(
        self, client: AsyncClient, test_user
    ):
        """Registration with an existing username returns 409 Conflict."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "different@example.com",
                "username": test_user["username"],  # Already exists
                "password": "SecurePass123!",
            },
        )
        assert resp.status_code == 409

    async def test_register_weak_password_fails(self, client: AsyncClient):
        """
        Weak password (no uppercase, no number) → 422 Validation Error.
        Our schema enforces password complexity.
        """
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "weak@example.com",
                "username": "weakuser",
                "password": "weakpassword",  # No uppercase, no number
            },
        )
        assert resp.status_code == 422

    async def test_register_too_long_password_fails(self, client: AsyncClient):
        """Password > 72 bytes fails validation (bcrypt hard limit)."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "long@example.com",
                "username": "longpwduser",
                "password": "A" * 73,  # 73 chars > 72-byte bcrypt limit
            },
        )
        assert resp.status_code == 422

    async def test_register_invalid_email_fails(self, client: AsyncClient):
        """Invalid email format → 422 Validation Error."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",
                "username": "user",
                "password": "SecurePass123!",
            },
        )
        assert resp.status_code == 422

    async def test_register_missing_required_fields(self, client: AsyncClient):
        """Missing required fields (email, username, password) → 422."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "only@example.com"},  # Missing username and password
        )
        assert resp.status_code == 422
        errors = resp.json()["details"]["errors"]
        field_names = [e["field"] for e in errors]
        assert "username" in field_names
        assert "password" in field_names


# =============================================================================
# LOGIN TESTS
# =============================================================================


class TestLogin:
    """Tests for POST /api/v1/auth/login."""

    async def test_login_success(self, client: AsyncClient, test_user):
        """Valid credentials return access + refresh tokens."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user["email"], "password": test_user["password"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_tokens_are_strings(self, client: AsyncClient, test_user):
        """Tokens are non-empty strings."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user["email"], "password": test_user["password"]},
        )
        data = resp.json()
        assert isinstance(data["access_token"], str)
        assert len(data["access_token"]) > 0
        assert isinstance(data["refresh_token"], str)
        assert len(data["refresh_token"]) > 0

    async def test_login_wrong_password_fails(self, client: AsyncClient, test_user):
        """Wrong password → 401 Unauthorized."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user["email"], "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_email_fails(self, client: AsyncClient):
        """Non-existent email → 401 Unauthorized (not 404 — avoid user enumeration)."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "SomePassword!"},
        )
        # Must be 401, not 404 — revealing that a user doesn't exist
        # is a security vulnerability (user enumeration attack)
        assert resp.status_code == 401

    async def test_login_missing_fields(self, client: AsyncClient):
        """Missing email or password → 422 Validation Error."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "only@example.com"},  # Missing password
        )
        assert resp.status_code == 422


# =============================================================================
# PROTECTED ENDPOINT TESTS
# =============================================================================


class TestProtectedEndpoints:
    """Tests for endpoints that require authentication."""

    async def test_get_me_authenticated(
        self, client: AsyncClient, auth_headers, test_user
    ):
        """Authenticated user can access /auth/me."""
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == test_user["email"]
        assert data["username"] == test_user["username"]

    async def test_get_me_unauthenticated_fails(self, client: AsyncClient):
        """Unauthenticated request to /auth/me → 401."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_get_me_invalid_token_fails(self, client: AsyncClient):
        """Invalid token → 401."""
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert resp.status_code == 401

    async def test_bearer_prefix_required(self, client: AsyncClient, test_user):
        """Token without 'Bearer ' prefix → 401 or 403."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user["email"], "password": test_user["password"]},
        )
        token = resp.json()["access_token"]

        # Missing "Bearer " prefix
        resp2 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": token},  # No "Bearer " prefix
        )
        assert resp2.status_code in (401, 403)


# =============================================================================
# HEALTH CHECK TESTS (no auth required)
# =============================================================================


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    async def test_health_live(self, client: AsyncClient):
        """GET /api/v1/health/live returns 200 with status=alive."""
        resp = await client.get("/api/v1/health/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alive"
        assert "timestamp" in data

    async def test_health_ready(self, client: AsyncClient):
        """GET /api/v1/health/ready returns 200 with database in checks."""
        resp = await client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        # Database must be healthy (Redis is optional/degraded is acceptable)
        assert data["checks"]["database"]["status"] == "healthy"
