"""
Expense and Category Pydantic Schemas
======================================
The contract between our API and the outside world.

Schema categories:
  *Create   → request body when creating a resource (required fields)
  *Update   → request body when updating (all fields optional — PATCH semantics)
  *Response → what we return to clients (controls what's exposed)
  *Filters  → query parameters for listing/filtering

Why PATCH semantics for Update schemas?
  PUT = replace entire resource (all fields required)
  PATCH = partial update (only send what changed)

  We use PATCH semantics: all fields in Update schemas are Optional.
  If a field is None (not sent), we don't update it.
  This means clients can update just the amount without resending description.

  Service pattern:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(expense, field, value)
  model_dump(exclude_none=True) → only returns fields the client actually sent.

Amount precision:
  We use Decimal for amounts, not float.
  float: 0.1 + 0.2 = 0.30000000000000004 (binary floating point error)
  Decimal: 0.1 + 0.2 = Decimal('0.3') (exact!)

  Pydantic's Decimal type with max_digits=12, decimal_places=2 validates that
  amount is at most 9,999,999,999.99 — the same constraint as NUMERIC(12,2).

Interview: "Update schemas use PATCH semantics — all fields optional.
model_dump(exclude_none=True) gives us only the fields the client sent,
so we update only what changed. This prevents accidentally overwriting
fields the client didn't intend to change."
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.expenses.models import CategoryType, RecurringFrequency

# =============================================================================
# CATEGORY SCHEMAS
# =============================================================================


class CategoryCreate(BaseModel):
    """
    POST /api/v1/categories request body.

    Users create custom categories (e.g., "Gym Membership", "Netflix").
    System default categories are seeded at startup and can't be created via API.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Category name",
        examples=["Gym Membership"],
    )

    icon: str | None = Field(
        default=None,
        max_length=10,
        description="Emoji or icon code for UI display",
        examples=["🏋️"],
    )

    # Validate hex color format: #RRGGBB (e.g., "#FF5733")
    color: str | None = Field(
        default=None,
        description="Hex color code for UI display (#RRGGBB)",
        examples=["#FF5733"],
    )

    category_type: CategoryType = Field(
        default=CategoryType.EXPENSE,
        description="Whether this is an expense, income, or both category",
    )

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("#") or len(v) != 7:
            raise ValueError("Color must be a hex code like #FF5733")
        try:
            int(v[1:], 16)  # Try to parse as hex
        except ValueError:
            raise ValueError("Color must be a valid hex code like #FF5733")
        return v.upper()


class CategoryUpdate(BaseModel):
    """
    PUT /api/v1/categories/{id} request body.

    All fields optional — PATCH semantics (only update what's sent).
    """

    name: str | None = Field(None, min_length=1, max_length=100)
    icon: str | None = None
    color: str | None = None
    category_type: CategoryType | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("#") or len(v) != 7:
            raise ValueError("Color must be a hex code like #FF5733")
        try:
            int(v[1:], 16)
        except ValueError:
            raise ValueError("Color must be a valid hex code like #FF5733")
        return v.upper()


class CategoryResponse(BaseModel):
    """
    Category data returned to clients.

    from_attributes=True: Pydantic reads field values from SQLAlchemy ORM attributes.
    Without this, model_validate(orm_object) would fail — Pydantic wouldn't know
    how to read values from an ORM object (which isn't a dict).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    icon: str | None
    color: str | None
    category_type: str  # CategoryType enum value as string
    is_default: bool  # True = system default, visible to all users
    is_system: bool = False  # computed below

    @classmethod
    def from_orm(cls, obj: object) -> CategoryResponse:
        """
        Custom factory that adds computed `is_system` field.
        is_system = True means the category belongs to no user (system-wide default).
        """
        from app.expenses.models import Category

        assert isinstance(obj, Category)
        data = cls.model_validate(obj)
        data.is_system = obj.user_id is None
        return data


# =============================================================================
# EXPENSE SCHEMAS
# =============================================================================


class ExpenseCreate(BaseModel):
    """
    POST /api/v1/expenses request body.

    Amount validation:
      gt=0: must be positive (can't have negative expense)
      max_digits=12, decimal_places=2: matches NUMERIC(12,2) in DB
    """

    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        description="Expense amount (positive, max 2 decimal places)",
        examples=[Decimal("49.99")],
    )

    description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="What was this expense for?",
        examples=["Monthly Netflix subscription"],
    )

    # Default: now (UTC). Client can specify a past date for historical entries.
    date: datetime = Field(
        default_factory=lambda: datetime.now().astimezone(),
        description="When the expense occurred (ISO 8601 datetime)",
        examples=["2026-05-27T10:00:00Z"],
    )

    category_id: uuid.UUID | None = Field(
        default=None,
        description="Category UUID (optional — expense can be uncategorized)",
    )

    tags: list[str] | None = Field(
        default=None,
        max_length=10,  # Max 10 tags per expense
        description="Tags for flexible grouping (e.g., ['business', 'travel'])",
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Additional notes",
    )

    location: str | None = Field(
        default=None,
        max_length=200,
        description="Where the expense occurred",
    )

    is_recurring: bool = Field(
        default=False,
        description="Set to true if this expense recurs automatically",
    )

    recurring_frequency: RecurringFrequency | None = Field(
        default=None,
        description="How often this recurs (required if is_recurring=True)",
    )

    recurring_end_date: datetime | None = Field(
        default=None,
        description="When to stop recurring (None = recur indefinitely)",
    )

    @field_validator("recurring_frequency")
    @classmethod
    def validate_recurring_frequency(
        cls, v: RecurringFrequency | None, info: object
    ) -> RecurringFrequency | None:
        """Enforce: if is_recurring=True, frequency must be set."""
        # info.data contains already-validated fields
        from pydantic import ValidationInfo

        if (
            isinstance(info, ValidationInfo)  # type: ignore[misc]
            and info.data.get("is_recurring")
            and v is None
        ):
            raise ValueError(
                "recurring_frequency is required when is_recurring is True"
            )
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        # Trim whitespace, lowercase, remove empties
        cleaned = [tag.strip().lower() for tag in v if tag.strip()]
        if len(cleaned) > 10:
            raise ValueError("Maximum 10 tags per expense")
        return cleaned or None


class ExpenseUpdate(BaseModel):
    """
    PUT /api/v1/expenses/{id} request body.

    PATCH semantics: all fields optional.
    Send only the fields you want to change.
    """

    amount: Decimal | None = Field(
        None, gt=Decimal("0"), max_digits=12, decimal_places=2
    )
    description: str | None = Field(None, min_length=1, max_length=500)
    date: datetime | None = None
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    notes: str | None = None
    location: str | None = None
    is_recurring: bool | None = None
    recurring_frequency: RecurringFrequency | None = None
    recurring_end_date: datetime | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = [tag.strip().lower() for tag in v if tag.strip()]
        if len(cleaned) > 10:
            raise ValueError("Maximum 10 tags per expense")
        return cleaned or None


class ExpenseResponse(BaseModel):
    """
    Expense data returned to clients.

    Includes the Category object (if present) — not just category_id.
    This avoids a second API call to fetch category details.

    The category field uses our CategoryResponse schema (nested response).
    SQLAlchemy loads it via selectinload (one extra query, not N+1).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    description: str
    date: datetime
    category_id: uuid.UUID | None
    category: CategoryResponse | None  # Nested response — no second API call needed
    tags: list[str] | None
    notes: str | None
    location: str | None
    is_recurring: bool
    recurring_frequency: str | None
    recurring_end_date: datetime | None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# FILTER SCHEMA — Query parameters for listing expenses
# =============================================================================


class ExpenseFilters(BaseModel):
    """
    Query parameter filters for GET /expenses.

    FastAPI can inject this entire model from query params using Depends():
      @router.get("/expenses")
      async def list_expenses(filters: ExpenseFilters = Depends()):
          ...

    This is much cleaner than 7 separate query params in the function signature.
    Pydantic validates each parameter just like request bodies.

    Example URL:
      GET /expenses?from_date=2026-05-01&to_date=2026-05-31&search=netflix&limit=10
    """

    # Date range filter (inclusive)
    from_date: datetime | None = Field(
        default=None,
        description="Filter expenses on or after this date",
    )
    to_date: datetime | None = Field(
        default=None,
        description="Filter expenses on or before this date",
    )

    # Category filter
    category_id: uuid.UUID | None = Field(
        default=None,
        description="Filter by category UUID",
    )

    # Amount range filter
    min_amount: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        description="Minimum expense amount",
    )
    max_amount: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        description="Maximum expense amount",
    )

    # Full-text search on description
    # ILIKE in PostgreSQL = case-insensitive LIKE
    # search="netflix" → WHERE description ILIKE '%netflix%'
    search: str | None = Field(
        default=None,
        max_length=200,
        description="Search term (matches description, case-insensitive)",
    )

    # Recurring filter
    is_recurring: bool | None = Field(
        default=None,
        description="Filter by recurring status",
    )

    # Pagination
    cursor: str | None = Field(
        default=None,
        description="Pagination cursor from previous response's next_cursor",
    )

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of results per page (1-100)",
    )
