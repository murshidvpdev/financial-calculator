"""
Authentication Pydantic Schemas
================================
Schemas serve as the "contract" between client and server.

Why separate schemas from models?
  SQLAlchemy models = database representation (ORM objects, has hashed_password)
  Pydantic schemas = API representation (what clients send/receive, no hashed_password)

  Never expose your ORM models directly as API responses!
  The ORM model has hashed_password, internal IDs, etc. — not safe to expose.

Schema categories:
  Request schemas: what clients send (INPUT — validated by FastAPI automatically)
  Response schemas: what server returns (OUTPUT — controls what data is exposed)

Pydantic v2 features used:
  - @field_validator: custom validation with clear error messages
  - model_config: control serialization behavior
  - Field(min_length=8, ...): declarative constraints
  - SecretStr: password field that's masked in logs/repr

Interview: "We separate Pydantic schemas from SQLAlchemy models.
Request schemas validate and sanitize input. Response schemas control
what data is returned to clients — we never accidentally expose
sensitive fields like hashed_password."
"""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# =============================================================================
# REQUEST SCHEMAS (what clients send to us)
# =============================================================================


class RegisterRequest(BaseModel):
    """
    POST /api/v1/auth/register request body.

    Validates:
    - Email format (pydantic's EmailStr does the heavy lifting)
    - Username: alphanumeric + underscore, 3-30 chars
    - Password: minimum 8 chars, must have uppercase, lowercase, and digit
    """

    email: EmailStr = Field(
        ...,  # ... means required (no default)
        description="Valid email address. Will be used for login.",
        examples=["user@example.com"],
    )

    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        description="Display username (alphanumeric and underscores only)",
        examples=["john_doe"],
    )

    password: str = Field(
        ...,
        min_length=8,
        max_length=72,  # bcrypt hard limit: only first 72 bytes are hashed
        description="Password (min 8 chars, max 72, must include uppercase, lowercase, digit)",
        examples=["SecurePass123"],
    )

    first_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional first name",
    )

    last_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional last name",
    )

    # @field_validator: runs AFTER Pydantic's built-in validation
    # 'before=True': runs BEFORE Pydantic's type coercion (useful for cleanup)
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Username must be alphanumeric + underscores only."""
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username can only contain letters, numbers, and underscores"
            )
        return v.lower()  # Store usernames lowercase for case-insensitive lookup

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Enforce password complexity.
        Industry standard: uppercase + lowercase + digit (no special char required
        as it causes usability issues without improving security much).
        """
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    """
    POST /api/v1/auth/login request body.

    Simple: just email and password.
    Why not username for login? Email is globally unique, username might not be.
    """

    email: EmailStr = Field(..., examples=["user@example.com"])
    password: str = Field(..., min_length=1, examples=["SecurePass123"])


class RefreshTokenRequest(BaseModel):
    """POST /api/v1/auth/refresh request body."""

    refresh_token: str = Field(..., description="The refresh token from login response")


class ChangePasswordRequest(BaseModel):
    """PUT /api/v1/users/me/password request body."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=72)  # bcrypt hard limit

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("New password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("New password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("New password must contain at least one digit")
        return v


class ForgotPasswordRequest(BaseModel):
    """POST /api/v1/auth/forgot-password request body."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """POST /api/v1/auth/reset-password request body."""

    token: str = Field(..., description="Password reset token from email")
    new_password: str = Field(..., min_length=8, max_length=72)  # bcrypt hard limit


# =============================================================================
# RESPONSE SCHEMAS (what we return to clients)
# =============================================================================


class UserResponse(BaseModel):
    """
    User data returned to clients.

    IMPORTANT: Does NOT include hashed_password, is_verified internals, etc.
    Only include what clients need and what's safe to expose.
    """

    # ConfigDict controls how the schema works
    # from_attributes=True: allows creating from SQLAlchemy ORM object (was orm_mode=True in v1)
    model_config = ConfigDict(from_attributes=True)

    # id is UUID in the ORM but Pydantic v2 serializes uuid.UUID → string in JSON automatically.
    # The client receives a plain string like "ef53adfd-8470-45a1-9aeb-dd7bce633201".
    id: uuid.UUID
    email: str
    username: str
    role: str
    is_active: bool
    is_verified: bool


class TokenResponse(BaseModel):
    """
    Response from /login and /refresh endpoints.

    Returns both tokens in the response body.
    In production you might use httpOnly cookies for the refresh token,
    but for API-first design, returning in body is simpler.
    """

    access_token: str = Field(..., description="JWT access token (expires in 30 min)")
    refresh_token: str = Field(..., description="JWT refresh token (expires in 7 days)")
    token_type: str = Field(default="bearer", description="OAuth2 token type")
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class RegisterResponse(BaseModel):
    """Response from /register endpoint."""

    message: str = "Registration successful"
    user: UserResponse


class MessageResponse(BaseModel):
    """Generic success message response."""

    message: str
