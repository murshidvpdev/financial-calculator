"""
Security Utilities — Password Hashing and JWT Tokens
======================================================
Two responsibilities:
  1. Password hashing (bcrypt) — for registration and login
  2. JWT token creation and verification — for authentication

Why bcrypt for password hashing?
  MD5:    insecure (rainbow tables crack in seconds)
  SHA256: insecure (too fast — attacker can try billions/second with GPU)
  bcrypt: designed for passwords! Intentionally slow (work factor = 12 rounds)
          Has built-in salt (no rainbow tables possible)
          Each hash takes ~100ms → 1M attempts/day max (vs billions with SHA256)

bcrypt hash anatomy:
  $2b$12$saltSaltSaltSaltSaltSahashHashHashHashHashHash
  |  |  |              |
  |  |  salt (22 chars) hash (31 chars)
  |  work factor (12 = 2^12 = 4096 rounds)
  version (2b = current)

Why we use bcrypt directly (not passlib):
  passlib wraps bcrypt and runs compatibility checks at initialization time.
  As of bcrypt 4.x+, those checks use passwords > 72 bytes to detect the
  "wrap bug," which bcrypt 5.x now rejects with a ValueError.
  Using bcrypt directly avoids this passlib compatibility issue while
  giving us exactly the same hashing behavior.

72-byte limit:
  bcrypt only hashes the first 72 bytes of a password. Longer passwords
  are silently truncated in older bcrypt versions; bcrypt 5.x raises ValueError.
  We enforce max_length=72 in Pydantic schemas to catch this at input validation.

Token Strategy:
  Access Token:
    - Short-lived: 30 minutes
    - Contains: user_id, role, token type
    - Sent in Authorization header
    - NOT stored in database (stateless)

  Refresh Token:
    - Long-lived: 7 days
    - Contains: user_id, token type, unique jti (JWT ID)
    - jti stored in Redis (for blacklisting on logout)
    - Used to get new access tokens without re-login

  Logout flow:
    1. Client sends refresh token to /logout
    2. Server adds refresh token's jti to Redis blacklist
    3. Token is now permanently invalid (even though it hasn't expired)
    4. Access token expires naturally (max 30 min before it's useless)

Interview: "We use bcrypt with work_factor=12 for passwords — it's intentionally
slow to prevent brute force. For JWT, we use HS256 with short-lived access tokens
(30min) and longer refresh tokens (7 days). Logout blacklists the refresh token
jti in Redis. We never store sensitive data in JWT payloads."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import structlog
from jose import JWTError, jwt

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# =============================================================================
# PASSWORD HASHING
# =============================================================================

# bcrypt work factor: 2^ROUNDS iterations
# 12 is the industry-recommended default (~100ms on modern hardware)
# Higher = slower = more secure (but worse UX). Don't go below 10.
BCRYPT_ROUNDS = 12


def hash_password(plain_password: str) -> str:
    """
    Hash a plain text password using bcrypt.

    bcrypt automatically:
    - Generates a cryptographically random salt
    - Applies the work factor (12 rounds = 4096 iterations)
    - Embeds the salt + rounds into the output hash

    Returns: "$2b$12$<salt><hash>" — everything needed to verify later

    NEVER: store plain_password, MD5/SHA of password, or reversible encryption
    ALWAYS: store the bcrypt hash and discard the plain text immediately
    """
    password_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against its bcrypt hash.

    bcrypt re-extracts the salt from hashed_password, hashes plain_password
    with that salt, and compares the result (constant-time comparison).

    Returns: True if correct, False otherwise
    Never raises — returns False for any error (malformed hash, etc.)
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:  # noqa: BLE001
        return False


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if a stored hash was created with fewer rounds than our current setting.

    Use this at login time to transparently upgrade old hashes:
      if security.needs_rehash(user.hashed_password):
          user.hashed_password = security.hash_password(plain_password)

    This gradually migrates all users to the current work factor without
    requiring a forced password reset.

    bcrypt hash format: $2b$<rounds>$<salt+hash>
    """
    try:
        parts = hashed_password.split("$")
        # "$2b$12$<data>" → ["", "2b", "12", "<data>"]
        rounds = int(parts[2])
        return rounds < BCRYPT_ROUNDS
    except (IndexError, ValueError):
        return True  # Malformed hash → force rehash


# =============================================================================
# JWT TOKEN OPERATIONS
# =============================================================================

# Token types — prevents a refresh token from being used as an access token
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_access_token(
    user_id: str,
    role: str,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a JWT access token.

    Payload claims:
      sub:  Subject — the user's UUID (who this token is for)
      type: "access" (prevents using refresh token as access token)
      role: User's RBAC role (avoids DB lookup on every request)
      iat:  Issued At (when token was created)
      exp:  Expiration (when token becomes invalid)
      jti:  JWT ID (unique identifier — enables targeted revocation)

    Why include role in the token?
      Avoids a database lookup on every authenticated request.
      Trade-off: if role changes, old tokens still have the old role until expiry.
      For immediate role changes, use short TTLs OR revoke via jti blacklist.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": user_id,  # Subject: who this token is for
        "type": ACCESS_TOKEN_TYPE,  # Token type: prevent token confusion attacks
        "role": role,  # RBAC role (avoid DB lookup on auth check)
        "iat": now,  # Issued At: for debugging, logging
        "exp": expire,  # Expiration: when token becomes invalid
        "jti": str(uuid.uuid4()),  # JWT ID: unique identifier for this token
    }

    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """
    Create a JWT refresh token.

    Returns: (token_string, jti)
    The jti is returned separately so it can be stored in Redis for blacklisting.

    Why return jti separately?
      On logout, we blacklist this token by jti in Redis.
      We store the jti (not the full token) — it's shorter and sufficient
      to uniquely identify and invalidate the specific token.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": user_id,
        "type": REFRESH_TOKEN_TYPE,
        "iat": now,
        "exp": expire,
        "jti": jti,
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    return token, jti


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT token.

    Verifies:
    1. Signature (was this signed with our secret?)
    2. Expiration (has it expired?)
    3. Algorithm (is it the expected algorithm — prevents algorithm confusion)

    Raises:
      JWTError: if token is invalid, expired, or tampered
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.warning("jwt_decode_failed", error=str(e))
        raise


def verify_access_token(token: str) -> dict[str, Any]:
    """
    Verify an access token and return its payload.

    Also checks the token type to prevent token confusion attacks
    (e.g., using a refresh token where an access token is expected).

    Raises: JWTError if invalid or wrong type
    """
    payload = decode_token(token)

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise JWTError("Invalid token type: expected access token")

    return payload


def verify_refresh_token(token: str) -> dict[str, Any]:
    """
    Verify a refresh token and return its payload.

    Also checks the token type to prevent token confusion attacks.

    Raises: JWTError if invalid or wrong type
    """
    payload = decode_token(token)

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise JWTError("Invalid token type: expected refresh token")

    return payload
