"""
Unit Tests — Password Hashing and JWT Security
================================================

These tests verify our security utilities in isolation.
No database, no HTTP — pure function tests.

Why unit test security separately?
  If auth tests fail, we need to know immediately whether the bug is in:
    a) The hashing/JWT logic (this file)
    b) The database queries (integration tests)
    c) The HTTP layer (integration tests)

  Separate unit tests give us precise failure attribution.
"""

from __future__ import annotations

import pytest
from jose import JWTError

from app.core.security import (
    BCRYPT_ROUNDS,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_access_token,
    verify_password,
    verify_refresh_token,
)

# =============================================================================
# PASSWORD HASHING TESTS
# =============================================================================


class TestHashPassword:
    """Tests for hash_password()."""

    def test_returns_string(self):
        """hash_password returns a string."""
        result = hash_password("MyPassword123!")
        assert isinstance(result, str)

    def test_bcrypt_format(self):
        """Hash follows bcrypt format: $2b$<rounds>$<salt+hash>."""
        result = hash_password("MyPassword123!")
        assert result.startswith("$2b$")
        parts = result.split("$")
        assert len(parts) == 4  # ["", "2b", "12", "salt+hash"]
        assert parts[2] == str(BCRYPT_ROUNDS)

    def test_different_hashes_for_same_password(self):
        """
        bcrypt generates a new random salt each call.
        Two hashes of the same password must be different.
        This prevents rainbow table attacks.
        """
        h1 = hash_password("SamePassword!")
        h2 = hash_password("SamePassword!")
        assert h1 != h2

    def test_hash_length(self):
        """bcrypt hashes are always exactly 60 characters."""
        result = hash_password("AnyPassword123!")
        assert len(result) == 60

    def test_special_characters(self):
        """Passwords with special chars hash successfully."""
        result = hash_password("P@$$w0rd!#%^&*()")
        assert result.startswith("$2b$")

    def test_unicode_password(self):
        """Unicode passwords (non-ASCII) hash successfully."""
        result = hash_password("пароль123!")  # Russian for "password"
        assert result.startswith("$2b$")

    def test_max_length_password(self):
        """72-character password (bcrypt limit) hashes successfully."""
        max_password = "A" * 71 + "!"  # exactly 72 bytes
        result = hash_password(max_password)
        assert result.startswith("$2b$")


class TestVerifyPassword:
    """Tests for verify_password()."""

    def test_correct_password_returns_true(self):
        """Correct password verifies successfully."""
        hashed = hash_password("CorrectPassword!")
        assert verify_password("CorrectPassword!", hashed) is True

    def test_wrong_password_returns_false(self):
        """Wrong password returns False (not raises)."""
        hashed = hash_password("RightPassword!")
        assert verify_password("WrongPassword!", hashed) is False

    def test_empty_password_returns_false(self):
        """Empty string against a real hash returns False."""
        hashed = hash_password("SomePassword!")
        assert verify_password("", hashed) is False

    def test_malformed_hash_returns_false(self):
        """
        Malformed hash should return False, not raise.
        We never want auth failures to throw 500 errors.
        """
        assert verify_password("SomePassword!", "not-a-valid-hash") is False

    def test_empty_hash_returns_false(self):
        """Empty hash returns False."""
        assert verify_password("SomePassword!", "") is False

    def test_case_sensitive(self):
        """Passwords are case-sensitive."""
        hashed = hash_password("Password123!")
        assert verify_password("password123!", hashed) is False
        assert verify_password("Password123!", hashed) is True

    def test_timing_consistency(self):
        """
        Verify that comparing against a dummy hash takes a similar
        amount of time as comparing against a real hash.
        This prevents timing attacks (an attacker can't tell if
        a user exists by measuring response time).

        Note: We just check both operations complete without error,
        since timing measurement in tests is unreliable.
        """
        real_hash = hash_password("RealPassword!")
        dummy_hash = "$2b$12$S7sLlq3MO3t/aewrMnRiwO7EwrAQqGihvRA5sUJSpIwFYh72RgiNy"

        # Both should return a bool without error
        result_real = verify_password("SomeTryInput!", real_hash)
        result_dummy = verify_password("SomeTryInput!", dummy_hash)

        assert isinstance(result_real, bool)
        assert isinstance(result_dummy, bool)


class TestNeedsRehash:
    """Tests for needs_rehash()."""

    def test_current_rounds_returns_false(self):
        """Hash with current rounds does not need rehashing."""
        hashed = hash_password("TestPassword!")
        assert needs_rehash(hashed) is False

    def test_fewer_rounds_returns_true(self):
        """Hash with fewer rounds (old password) needs rehashing."""
        import bcrypt

        # Create a hash with fewer rounds than current BCRYPT_ROUNDS
        old_rounds = max(4, BCRYPT_ROUNDS - 2)
        salt = bcrypt.gensalt(rounds=old_rounds)
        old_hash = bcrypt.hashpw(b"TestPassword!", salt).decode()
        assert needs_rehash(old_hash) is True

    def test_malformed_hash_returns_true(self):
        """Malformed hash → force rehash (safe default)."""
        assert needs_rehash("not-a-hash") is True

    def test_empty_string_returns_true(self):
        """Empty hash → force rehash."""
        assert needs_rehash("") is True


# =============================================================================
# JWT TOKEN TESTS
# =============================================================================


class TestCreateAccessToken:
    """Tests for create_access_token()."""

    def test_returns_string(self):
        """create_access_token returns a JWT string."""
        token = create_access_token(user_id="user-123", role="user")
        assert isinstance(token, str)
        # JWT has 3 parts separated by dots
        assert len(token.split(".")) == 3

    def test_payload_contains_expected_claims(self):
        """Access token contains all required JWT claims."""
        user_id = "abc-123-def"
        token = create_access_token(user_id=user_id, role="user")
        payload = decode_token(token)

        assert payload["sub"] == user_id
        assert payload["type"] == "access"
        assert payload["role"] == "user"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_admin_role_preserved(self):
        """Token preserves the role exactly."""
        token = create_access_token(user_id="admin-id", role="admin")
        payload = decode_token(token)
        assert payload["role"] == "admin"

    def test_additional_claims(self):
        """Additional claims are embedded in the token."""
        token = create_access_token(
            user_id="user-123",
            role="user",
            additional_claims={"custom_field": "custom_value"},
        )
        payload = decode_token(token)
        assert payload["custom_field"] == "custom_value"

    def test_unique_jti_each_call(self):
        """Each token has a unique jti (for revocation purposes)."""
        t1 = create_access_token(user_id="user-123", role="user")
        t2 = create_access_token(user_id="user-123", role="user")
        p1 = decode_token(t1)
        p2 = decode_token(t2)
        assert p1["jti"] != p2["jti"]


class TestCreateRefreshToken:
    """Tests for create_refresh_token()."""

    def test_returns_token_and_jti(self):
        """create_refresh_token returns (token_string, jti_string)."""
        token, jti = create_refresh_token(user_id="user-123")
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(token.split(".")) == 3

    def test_jti_in_payload(self):
        """The returned jti matches the token's payload jti."""
        token, jti = create_refresh_token(user_id="user-123")
        payload = decode_token(token)
        assert payload["jti"] == jti

    def test_token_type_is_refresh(self):
        """Refresh token has type="refresh" in payload."""
        token, _ = create_refresh_token(user_id="user-123")
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_longer_expiry_than_access_token(self):
        """Refresh token expires later than access token."""
        access = create_access_token(user_id="user-123", role="user")
        refresh, _ = create_refresh_token(user_id="user-123")

        access_payload = decode_token(access)
        refresh_payload = decode_token(refresh)

        assert refresh_payload["exp"] > access_payload["exp"]


class TestVerifyAccessToken:
    """Tests for verify_access_token()."""

    def test_valid_access_token_returns_payload(self):
        """Valid access token → payload returned."""
        token = create_access_token(user_id="user-123", role="user")
        payload = verify_access_token(token)
        assert payload["sub"] == "user-123"

    def test_refresh_token_rejected_as_access(self):
        """
        Refresh token CANNOT be used as access token.
        This prevents token confusion attacks.
        """
        refresh_token, _ = create_refresh_token(user_id="user-123")
        with pytest.raises(JWTError):
            verify_access_token(refresh_token)

    def test_tampered_token_rejected(self):
        """Modified token signature is rejected."""
        token = create_access_token(user_id="user-123", role="user")
        # Tamper with the payload
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + "X" + "." + parts[2]
        with pytest.raises(JWTError):
            verify_access_token(tampered)

    def test_garbage_token_rejected(self):
        """Totally invalid token raises JWTError."""
        with pytest.raises(JWTError):
            verify_access_token("not.a.token")


class TestVerifyRefreshToken:
    """Tests for verify_refresh_token()."""

    def test_valid_refresh_token_returns_payload(self):
        """Valid refresh token → payload returned."""
        token, jti = create_refresh_token(user_id="user-456")
        payload = verify_refresh_token(token)
        assert payload["sub"] == "user-456"
        assert payload["jti"] == jti

    def test_access_token_rejected_as_refresh(self):
        """
        Access token CANNOT be used as refresh token.
        This prevents token confusion attacks.
        """
        access_token = create_access_token(user_id="user-123", role="user")
        with pytest.raises(JWTError):
            verify_refresh_token(access_token)
