"""
Authentication Router
=====================
HTTP endpoints for authentication operations.

Router is the HTTP layer ONLY:
  - Parse request (FastAPI does this automatically via Pydantic schemas)
  - Call the service (business logic lives in AuthService)
  - Return the response (Pydantic serializes to JSON)

Design principles:
  - Handlers are thin (< 10 lines of logic)
  - Business logic lives in service, not here
  - Consistent response format using schemas

Rate limiting:
  Auth endpoints are especially sensitive to brute force.
  We rate limit /login to 10 requests/minute per IP.
  /register is rate limited to 5/minute (prevent mass account creation).

Interview: "Our auth router delegates all business logic to AuthService.
The router's job is HTTP — parse request, call service, form response.
We apply stricter rate limiting to auth endpoints than regular API endpoints."
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
)
from app.auth.service import AuthService
from app.database import get_db
from app.dependencies import CurrentUser

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,  # 201 Created (not 200 OK — resource was created)
    summary="Register a new user account",
    description="""
Create a new user account.

**Password requirements:**
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit

**Username requirements:**
- 3-30 characters
- Letters, numbers, and underscores only
    """,
)
async def register(
    request_data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """
    Register a new user.

    FastAPI automatically:
    1. Parses JSON body into RegisterRequest (validates all fields)
    2. Returns 422 if validation fails (with detailed error message)
    3. Calls this function with the validated data

    We then call AuthService.register_user() which does the heavy lifting.
    """
    service = AuthService(db)
    user = await service.register_user(request_data)

    return RegisterResponse(
        message=(
            "Registration successful! Please check your email to verify your account."
            if False  # email verification disabled for now
            else "Registration successful!"
        ),
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=200,
    summary="Login with email and password",
    description="Authenticate and receive JWT access + refresh tokens.",
)
async def login(
    request: Request,
    request_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Login endpoint.

    Returns access token (30 min) and refresh token (7 days).

    Security: same error for wrong email AND wrong password.
    This prevents user enumeration attacks.
    """
    service = AuthService(db)
    _user, token_response = await service.login_user(request_data)

    return token_response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=200,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access + refresh token pair.",
)
async def refresh_token(
    request_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Refresh tokens endpoint.

    Token rotation: old refresh token is invalidated, new pair is issued.
    This limits the damage if a refresh token is stolen.
    """
    service = AuthService(db)
    return await service.refresh_tokens(request_data.refresh_token)


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=200,
    summary="Logout (invalidate refresh token)",
    description="Blacklist the refresh token so it cannot be used again.",
)
async def logout(
    request_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Logout endpoint.

    Blacklists the refresh token in Redis.
    The access token expires naturally (max 30 minutes).
    Client should delete both tokens from storage.
    """
    service = AuthService(db)
    await service.logout_user(request_data.refresh_token)

    return MessageResponse(message="Logged out successfully")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=200,
    summary="Get current user info",
    description="Returns the currently authenticated user's information.",
)
async def get_me(current_user: CurrentUser) -> UserResponse:
    """
    Get current user endpoint.

    Protected endpoint — requires valid access token.
    FastAPI calls get_current_active_user dependency automatically.
    If token is invalid, dependency raises UnauthorizedError before this runs.

    This is the simplest protected endpoint pattern.
    """
    return UserResponse.model_validate(current_user)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=200,
    summary="Request password reset email",
)
async def forgot_password(
    request_data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Password reset request.

    Security: ALWAYS returns success (even if email doesn't exist).
    This prevents email enumeration — attacker can't tell if email is registered.

    TODO Phase 7: Implement actual email sending via Celery + SES.
    For now, just log the request.
    """
    logger.info("password_reset_requested", email=str(request_data.email))

    # TODO: Generate reset token, store in Redis with 1hr TTL, send email
    # For now, just return success message (safe to return even for unknown emails)

    return MessageResponse(
        message="If that email is registered, you'll receive a password reset link shortly."
    )
