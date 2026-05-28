"""
Unit Tests — Cursor Pagination Utilities
==========================================

Tests for encode_cursor / decode_cursor in app.core.pagination.
These are pure utility functions — no database needed.

Round-trip property: decode(encode(date, id)) == (date, id)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.pagination import decode_cursor, encode_cursor

# =============================================================================
# ENCODE / DECODE ROUND-TRIP TESTS
# =============================================================================


class TestCursorRoundTrip:
    """Verify that encode → decode round-trips correctly."""

    def test_basic_round_trip(self):
        """encode then decode returns the original (date, id) pair."""
        original_date = datetime(2026, 5, 27, 10, 30, 0, tzinfo=UTC)
        original_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

        cursor = encode_cursor(original_date, original_id)
        decoded_date, decoded_id = decode_cursor(cursor)

        assert decoded_date == original_date
        assert decoded_id == original_id

    def test_round_trip_with_microseconds(self):
        """Microseconds in datetime are preserved."""
        original_date = datetime(2026, 1, 15, 8, 45, 30, 123456, tzinfo=UTC)
        original_id = uuid.uuid4()

        cursor = encode_cursor(original_date, original_id)
        decoded_date, decoded_id = decode_cursor(cursor)

        assert decoded_date == original_date
        assert decoded_id == original_id

    def test_different_dates_produce_different_cursors(self):
        """Two different dates produce different cursors (no collision)."""
        id1 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        date1 = datetime(2026, 5, 1, tzinfo=UTC)
        date2 = datetime(2026, 5, 2, tzinfo=UTC)

        cursor1 = encode_cursor(date1, id1)
        cursor2 = encode_cursor(date2, id1)

        assert cursor1 != cursor2

    def test_different_ids_produce_different_cursors(self):
        """Same date, different IDs produce different cursors."""
        date = datetime(2026, 5, 1, tzinfo=UTC)
        id1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
        id2 = uuid.UUID("22222222-2222-2222-2222-222222222222")

        cursor1 = encode_cursor(date, id1)
        cursor2 = encode_cursor(date, id2)

        assert cursor1 != cursor2


class TestEncodeCursor:
    """Tests for encode_cursor() output format."""

    def test_returns_string(self):
        """encode_cursor returns a string."""
        cursor = encode_cursor(
            datetime(2026, 5, 27, tzinfo=UTC),
            uuid.uuid4(),
        )
        assert isinstance(cursor, str)

    def test_url_safe_characters_only(self):
        """
        Cursor must be URL-safe (no +, /, = that need percent-encoding).
        We use base64url encoding (uses - and _ instead of + and /).
        """
        cursor = encode_cursor(
            datetime(2026, 5, 27, tzinfo=UTC),
            uuid.uuid4(),
        )
        # base64url alphabet: A-Z, a-z, 0-9, -, _
        # We DON'T use padding (=)
        unsafe_chars = set("+/=")
        assert not any(
            c in cursor for c in unsafe_chars
        ), f"Cursor contains URL-unsafe chars: {cursor}"

    def test_cursor_is_not_empty(self):
        """Cursor is never an empty string."""
        cursor = encode_cursor(
            datetime(2026, 5, 27, tzinfo=UTC),
            uuid.uuid4(),
        )
        assert len(cursor) > 0


class TestDecodeCursor:
    """Tests for decode_cursor() error handling."""

    def test_invalid_base64_raises_value_error(self):
        """Non-base64 input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor("this is not valid base64!!!")

    def test_valid_base64_invalid_json_raises_value_error(self):
        """Valid base64 but not JSON raises ValueError."""
        import base64

        bad_json = base64.urlsafe_b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor(bad_json)

    def test_json_missing_keys_raises_value_error(self):
        """JSON without 'd' and 'i' keys raises ValueError."""
        import base64
        import json

        bad_payload = base64.urlsafe_b64encode(
            json.dumps({"wrong": "keys"}).encode()
        ).decode()
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor(bad_payload)

    def test_invalid_uuid_raises_value_error(self):
        """JSON with invalid UUID raises ValueError."""
        import base64
        import json

        bad_payload = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "d": "2026-05-27T10:00:00+00:00",
                    "i": "not-a-uuid",
                }
            ).encode()
        ).decode()
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor(bad_payload)

    def test_empty_string_raises_value_error(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            decode_cursor("")
