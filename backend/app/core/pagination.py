"""
Cursor-Based Pagination
========================
Reusable pagination utility used by expenses, income, and other list endpoints.

WHY cursor pagination over offset pagination:

  Offset pagination (how most tutorials teach it):
    GET /expenses?page=1&per_page=20  → OFFSET 0 LIMIT 20
    GET /expenses?page=501&per_page=20 → OFFSET 10000 LIMIT 20 ← SLOW!

    PostgreSQL must scan ALL 10,020 rows to return page 501.
    As your dataset grows, deep pages get slower and slower.
    Another problem: if a new record is inserted between requests,
    you get duplicate or skipped items.

  Cursor pagination (the right way):
    GET /expenses                       → Returns 20 items + cursor="eyJkIjoi..."
    GET /expenses?cursor=eyJkIjoi...    → Returns next 20, jumping directly

    The cursor encodes the sort position of the last seen item.
    PostgreSQL uses the index to find it — O(log N) not O(N).
    No duplicates or skips with concurrent inserts.

How our cursor works:
  We sort by (date DESC, id DESC).
  The cursor encodes the last item's {date, id} as base64(JSON).
  Next page query: WHERE date < cursor_date OR (date = cursor_date AND id < cursor_id)
  This skips everything already seen and starts from the next position.

Decoding example:
  cursor = "eyJkIjogIjIwMjYtMDUtMjdUMTA6MDA6MDArMDA6MDAiLCAiaSI6ICJ1dWlkLWhlcmUifQ=="
  → {"d": "2026-05-27T10:00:00+00:00", "i": "uuid-here"}
  → Filter: date < 2026-05-27T10:00:00+00:00 OR (date = ... AND id < "uuid-here")

Interview: "We use cursor-based pagination. Offset pagination's performance
degrades with dataset size — OFFSET 10000 forces a full scan. Cursor pagination
encodes the sort position of the last item, letting PostgreSQL jump directly
to that position using the index. It's also stable: inserts between pages
don't cause duplicates or skips."
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


# =============================================================================
# PAGE RESPONSE — Generic paginated response wrapper
# =============================================================================


class Page(BaseModel, Generic[T]):
    """
    Generic paginated response.

    Generic[T] means the type of `items` is declared by the caller:
      Page[ExpenseResponse]  → items is list[ExpenseResponse]
      Page[CategoryResponse] → items is list[CategoryResponse]

    Usage in endpoint:
      @router.get("/expenses", response_model=Page[ExpenseResponse])
      async def list_expenses(...) -> Page[ExpenseResponse]:
          ...
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T]

    # Total count is OPTIONAL — computing COUNT(*) on filtered large tables
    # can be slow. We skip it for performance and use has_next instead.
    total: int | None = None

    # True if there are more results after this page
    has_next: bool

    # Opaque cursor string to pass as ?cursor= for the next page
    # None if there are no more results (last page)
    next_cursor: str | None

    # How many items were requested per page
    limit: int


# =============================================================================
# CURSOR ENCODING / DECODING
# =============================================================================


def encode_cursor(date: datetime, item_id: uuid.UUID) -> str:
    """
    Encode a (date, id) pair into an opaque cursor string.

    Why base64?
      - Opaque: clients treat it as a black box (don't parse it)
      - URL-safe: can be passed as a query parameter
      - Hides implementation: we can change the cursor format without
        breaking API contracts (clients just pass it back to us)

    Format: base64url(json({"d": "2026-05-27T10:00:00+00:00", "i": "uuid"}))
    """
    payload = {
        "d": date.isoformat(),  # date → ISO 8601 string (timezone-aware)
        "i": str(item_id),  # UUID → standard string form
    }
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    # Strip "=" padding — base64url without padding is cleaner in URLs
    # The decoder adds padding back before decoding
    return base64.urlsafe_b64encode(json_bytes).decode("utf-8").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """
    Decode a cursor string back into (date, id).

    Raises ValueError if the cursor is malformed (tampered, expired format, etc.)
    We treat all cursor errors the same — invalid cursor → start from beginning.
    """
    try:
        # Add back stripped "=" padding: base64 length must be multiple of 4
        padded = cursor + "=" * (4 - len(cursor) % 4) if len(cursor) % 4 else cursor
        json_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))
        payload = json.loads(json_bytes)
        date = datetime.fromisoformat(payload["d"])
        item_id = uuid.UUID(payload["i"])
        return date, item_id
    except Exception as e:
        raise ValueError(f"Invalid pagination cursor: {e}") from e
