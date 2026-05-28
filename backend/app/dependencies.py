"""
FastAPI Dependencies
=====================
Dependencies are the cornerstone of FastAPI's design.
They implement Dependency Injection — functions that are called
automatically by FastAPI before your handler runs.

Why Dependency Injection?
  Without DI:
    @router.get("/expenses")
    async def list_expenses(request: Request):
        token = request.headers.get("Authorization")
        payload = decode_token(token)  # repeated in every endpoint!
        user_id = payload["sub"]
        db = get_database_session()    # repeated in every endpoint!
        ...

  With DI:
    @router.get("/expenses")
    async def list_expenses(
        user: User = Depends(get_current_user),  # ← FastAPI calls this automatically
        db: AsyncSession = Depends(get_db),      # ← And this
    ):
        # user is already verified! db session is already open!
        ...

Benefits:
  - Reusable: write get_current_user once, use it everywhere
  - Testable: override dependencies in tests with mock implementations
  - Composable: dependencies can depend on other dependencies
  - Declarative: the handler signature shows all its requirements

Dependency hierarchy:
  get_db → get_current_user → require_verified_user → require_active_user
                                      ↓
                               get_admin_user (role check)
                               get_super_admin_user

Interview: "FastAPI's dependency injection is one of its strongest features.
Authentication is a dependency — get_current_user is declared in the handler
signature. FastAPI resolves it before calling the handler. Dependencies are
reusable and testable. In tests, we override dependencies with mocks."
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_access_token
from app.database import get_db
from app.exceptions import ForbiddenError, InvalidTokenError, UnauthorizedError
from app.users.models import User, UserRole

logger = structlog.get_logger(__name__)

# HTTPBearer: Parses "Authorization: Bearer <token>" header
# auto_error=False: don't automatically raise 403 if header is missing
#   (we want to raise our custom UnauthorizedError instead)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and verify the current user from JWT token.

    Accepts token from TWO sources (in priority order):
      1. Authorization: Bearer <token>  header  (API clients, mobile apps)
      2. access_token httpOnly cookie           (browser / HTMX requests)

    This dual-source auth is what makes HTMX work seamlessly:
      - HTMX forms post to the same /api/v1/* endpoints as the JS/mobile clients
      - The browser automatically sends the httpOnly cookie on every request
      - The API endpoint validates the cookie just like a Bearer token
      - No Authorization header needed in HTMX hx-headers

    Security:
      - httpOnly cookie: JS cannot read it (XSS protection)
      - samesite=lax cookie: not sent cross-site (CSRF protection)
      - Bearer token still works for all non-browser API consumers
    """
    # 1. Try Authorization: Bearer <token> header first
    token: str | None = None
    if credentials:
        token = credentials.credentials
    # 2. Fall back to httpOnly cookie (sent automatically by the browser)
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise UnauthorizedError(
            message="Authentication required. Include 'Authorization: Bearer <token>' header."
        )

    try:
        payload = verify_access_token(token)
    except JWTError:
        raise InvalidTokenError()

    user_id = payload.get("sub")
    if not user_id:
        raise InvalidTokenError()

    # Load user from database
    # We do this on every request to ensure:
    # 1. User still exists (account not deleted)
    # 2. User is still active (not banned after token was issued)
    from app.auth.service import AuthService

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if not user:
        raise InvalidTokenError()

    # Bind user_id to structlog context
    # All log entries within this request will include the user_id
    structlog.contextvars.bind_contextvars(user_id=str(user.id))

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency that ensures the user is active.

    Builds on get_current_user.
    If get_current_user succeeds (user exists), this checks is_active.
    """
    if not current_user.is_active:
        raise ForbiddenError(message="Your account has been deactivated.")
    return current_user


async def get_verified_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Dependency that ensures the user's email is verified.

    Only used if email verification is enabled (controlled by feature flag).
    """
    from app.config import get_settings

    settings = get_settings()

    if settings.enable_email_verification and not current_user.is_verified:
        raise ForbiddenError(
            message="Please verify your email address to access this feature."
        )
    return current_user


def require_role(*roles: UserRole):
    """
    Factory function that creates a role-checking dependency.

    Usage:
        @router.get("/admin/users")
        async def list_all_users(
            user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPER_ADMIN))
        ):
            ...

    This is the RBAC (Role-Based Access Control) implementation.
    The factory pattern allows dynamic role requirements per endpoint.
    """

    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in roles:
            raise ForbiddenError(
                message=f"Access denied. Required role: {', '.join(r.value for r in roles)}"
            )
        return current_user

    return role_checker


# Pre-built role dependencies for common use cases
# Usage: user: User = Depends(get_admin_user)
get_admin_user = require_role(UserRole.ADMIN, UserRole.SUPER_ADMIN)
get_super_admin_user = require_role(UserRole.SUPER_ADMIN)

# Type aliases for cleaner handler signatures
# Usage:
#   async def my_handler(user: CurrentUser, db: DB):
CurrentUser = Annotated[User, Depends(get_current_active_user)]
VerifiedUser = Annotated[User, Depends(get_verified_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
