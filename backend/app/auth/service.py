"""
Authentication Service
=======================
Business logic for authentication operations.

Service Layer Pattern:
  Router (HTTP) → Service (Business Logic) → Repository (Database)

Why a service layer?
  - Router handles HTTP (parsing requests, forming responses)
  - Service handles business logic (validate, hash, create, verify)
  - Database operations could be in service or separate repository

  This separation means:
  - Testing service in isolation (no HTTP, no database)
  - Reusing business logic from multiple places (API, CLI, workers)
  - Clear responsibility boundaries

What this service does:
  - register_user: validate uniqueness, hash password, create user+profile
  - login_user: verify credentials, create tokens
  - refresh_tokens: verify refresh token, issue new pair
  - logout_user: blacklist refresh token in Redis
  - get_current_user: validate access token, return user data

Interview: "Authentication logic lives in a service class, separate from
the HTTP router. This makes it testable in isolation and reusable.
The service depends on SQLAlchemy sessions and Redis — both injected
via FastAPI's dependency injection, making testing easy with mocks."
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from app.cache import cache_delete, cache_get, cache_set
from app.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    needs_rehash,
    verify_password,
    verify_refresh_token,
)
from app.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from app.users.models import User, UserProfile, UserRole

logger = structlog.get_logger(__name__)
settings = get_settings()

# Redis key prefix for blacklisted tokens
# Good practice: prefix all Redis keys with the context to avoid collisions
BLACKLISTED_TOKEN_PREFIX = "blacklist:refresh:"


class AuthService:
    """
    Authentication business logic service.

    Injected with database session (AsyncSession) on each request.
    Redis client accessed via module-level functions (stateless).

    Design: class-based for grouping related methods, but could also be
    standalone functions. Class makes mocking in tests slightly easier.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register_user(self, data: RegisterRequest) -> User:
        """
        Register a new user account.

        Steps:
        1. Check if email already exists (prevent duplicate accounts)
        2. Check if username already exists
        3. Hash the password (NEVER store plain text)
        4. Create User record
        5. Create UserProfile record (linked to User)
        6. Commit to database

        Raises:
          EmailAlreadyExistsError: if email is taken
          ConflictError: if username is taken
        """
        # Step 1: Check email uniqueness
        # SELECT 1 FROM users WHERE email = :email LIMIT 1
        existing_email = await self.db.execute(
            select(User).where(User.email == str(data.email)).limit(1)
        )
        if existing_email.scalar_one_or_none():
            raise EmailAlreadyExistsError(email=str(data.email))

        # Step 2: Check username uniqueness
        existing_username = await self.db.execute(
            select(User).where(User.username == data.username).limit(1)
        )
        if existing_username.scalar_one_or_none():
            from app.exceptions import ConflictError

            raise ConflictError(
                message=f"Username '{data.username}' is already taken",
                details={"username": data.username},
            )

        # Step 3: Hash the password
        # hash_password is CPU-intensive (bcrypt rounds) — in high-traffic apps,
        # consider running in a thread pool: await asyncio.to_thread(hash_password, password)
        hashed = hash_password(data.password)

        # Step 4: Create User record
        user = User(
            email=str(data.email),
            username=data.username,
            hashed_password=hashed,
            role=UserRole.USER,
            is_active=True,
            is_verified=not settings.enable_email_verification,
            # If email verification is disabled, auto-verify on registration
        )
        self.db.add(user)
        # flush() sends SQL to DB but doesn't commit
        # We need user.id to exist before creating UserProfile (FK reference)
        await self.db.flush()

        # Step 5: Create UserProfile linked to the new user
        profile = UserProfile(
            user_id=user.id,
            first_name=data.first_name,
            last_name=data.last_name,
        )
        self.db.add(profile)

        # Step 6: Commit both user and profile atomically
        # If anything fails, both are rolled back (transaction)
        await self.db.commit()
        await self.db.refresh(user)  # Reload to get server-side defaults

        logger.info(
            "user_registered",
            user_id=str(user.id),
            email=user.email,
            username=user.username,
        )

        return user

    async def login_user(self, data: LoginRequest) -> tuple[User, TokenResponse]:
        """
        Authenticate a user and return JWT tokens.

        Steps:
        1. Find user by email
        2. Verify password against stored bcrypt hash
        3. Check user is active (not banned/deactivated)
        4. Create access + refresh tokens
        5. Store refresh token jti in Redis (for blacklist check on refresh/logout)
        6. Optionally: re-hash password if work factor increased

        Security: SAME error message for "wrong email" and "wrong password"
        This prevents user enumeration (attacker can't tell if email exists)

        Returns: (user, token_response)
        """
        # Step 1: Find user by email
        result = await self.db.execute(
            select(User)
            .where(
                User.email == str(data.email),
                User.deleted_at.is_(None),  # Soft-delete filter
            )
            .limit(1)
        )
        user = result.scalar_one_or_none()

        # Step 2: Verify password (even if user not found, to prevent timing attacks)
        # Timing attack: if we return immediately for "user not found", an attacker
        # can detect valid emails by measuring response time.
        # Solution: always call verify_password (even with a dummy hash if user not found).
        #
        # DUMMY_HASH is a real, pre-computed bcrypt hash of a throwaway string.
        # It must be a structurally valid bcrypt hash — otherwise bcrypt.checkpw()
        # raises ValueError before doing any work, which would SHORTEN the response
        # for unknown users and defeat the timing-attack mitigation.
        #
        # How this was generated (run once, then hardcoded):
        #   import bcrypt
        #   bcrypt.hashpw(b"timing_dummy_not_real", bcrypt.gensalt(rounds=12))
        dummy_hash = "$2b$12$S7sLlq3MO3t/aewrMnRiwO7EwrAQqGihvRA5sUJSpIwFYh72RgiNy"  # noqa: S105
        password_ok = verify_password(
            data.password,
            user.hashed_password if user else dummy_hash,
        )

        if not user or not password_ok:
            raise InvalidCredentialsError()

        # Step 3: Check if account is active
        if not user.is_active:
            raise InvalidCredentialsError()  # Same error — don't reveal account status

        # Step 4: Create tokens
        access_token = create_access_token(
            user_id=str(user.id),
            role=user.role.value,
        )
        refresh_token, refresh_jti = create_refresh_token(user_id=str(user.id))

        # Step 5: Store refresh token jti in Redis (TTL = refresh token lifetime)
        ttl_seconds = settings.refresh_token_expire_days * 24 * 60 * 60
        await cache_set(
            key=f"refresh_jti:{refresh_jti}",
            value=str(user.id),
            ttl_seconds=ttl_seconds,
        )

        # Step 6: Rehash if bcrypt work factor changed
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(data.password)
            await self.db.commit()
            logger.info("password_rehashed", user_id=str(user.id))

        logger.info(
            "user_logged_in",
            user_id=str(user.id),
            email=user.email,
        )

        token_response = TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )

        return user, token_response

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """
        Exchange a valid refresh token for a new access + refresh token pair.

        Token Rotation: we issue a NEW refresh token and invalidate the old one.
        This provides better security (if old token is stolen, it's useless after rotation).

        Steps:
        1. Verify refresh token signature + expiry
        2. Check refresh token jti is not blacklisted in Redis
        3. Verify user still exists and is active
        4. Issue new token pair
        5. Blacklist old refresh token jti
        6. Store new refresh token jti
        """
        # Step 1: Verify token
        try:
            payload = verify_refresh_token(refresh_token)
        except Exception:
            raise InvalidTokenError()

        user_id = payload.get("sub")
        old_jti = payload.get("jti")

        if not user_id or not old_jti:
            raise InvalidTokenError()

        # Step 2: Check if refresh token is blacklisted
        blacklisted = await cache_get(f"{BLACKLISTED_TOKEN_PREFIX}{old_jti}")
        if blacklisted:
            logger.warning("blacklisted_token_used", user_id=user_id, jti=old_jti)
            raise InvalidTokenError()

        # Also check the jti is still "live" in Redis (proves it was issued by us)
        live_jti = await cache_get(f"refresh_jti:{old_jti}")
        if not live_jti:
            raise InvalidTokenError()

        # Step 3: Verify user still exists and is active
        result = await self.db.execute(
            select(User)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .limit(1)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise InvalidTokenError()

        # Step 4: Create new token pair
        new_access_token = create_access_token(
            user_id=str(user.id),
            role=user.role.value,
        )
        new_refresh_token, new_jti = create_refresh_token(user_id=str(user.id))

        # Step 5: Blacklist old refresh token jti
        # TTL = 1 day (enough to cover any existing requests using old token)
        await cache_set(
            key=f"{BLACKLISTED_TOKEN_PREFIX}{old_jti}",
            value="1",
            ttl_seconds=86400,
        )

        # Also remove old jti from live set
        await cache_delete(f"refresh_jti:{old_jti}")

        # Step 6: Store new refresh token jti
        ttl_seconds = settings.refresh_token_expire_days * 24 * 60 * 60
        await cache_set(
            key=f"refresh_jti:{new_jti}",
            value=str(user.id),
            ttl_seconds=ttl_seconds,
        )

        logger.info("tokens_refreshed", user_id=str(user.id))

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )

    async def logout_user(self, refresh_token: str) -> None:
        """
        Logout: blacklist the refresh token so it can't be used to get new tokens.

        The access token will expire naturally (max 30 minutes).
        The refresh token is permanently invalidated by adding its jti to blacklist.

        This is the standard JWT logout pattern when not using httpOnly cookies.
        """
        try:
            payload = verify_refresh_token(refresh_token)
            jti = payload.get("jti")
            user_id = payload.get("sub")

            if jti:
                await cache_set(
                    key=f"{BLACKLISTED_TOKEN_PREFIX}{jti}",
                    value="1",
                    ttl_seconds=settings.refresh_token_expire_days * 24 * 60 * 60,
                )
                await cache_delete(f"refresh_jti:{jti}")

            logger.info("user_logged_out", user_id=user_id)
        except Exception:
            # Even if token is invalid, logout "succeeds" (idempotent)
            pass

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Fetch a user by ID. Used by auth dependency."""
        result = await self.db.execute(
            select(User)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
