"""
Expense, Income, and Category Database Models
==============================================
Core financial data models for the Finance Calculator.

Note: `from __future__ import annotations` makes all type annotations lazy strings.
This allows forward references to models in other modules without circular imports.
SQLAlchemy resolves these string references at runtime.

Design Decisions:
  1. Category is shared between Expense and Income
     (Both can have categories like "Salary" income or "Food" expense)
  2. Recurring transactions reference themselves (self-referential)
  3. Tags stored as array (PostgreSQL ARRAY type)
  4. Amount stored as Numeric(12,2) — NOT float!

Why Numeric instead of Float for money?
  Float: 0.1 + 0.2 = 0.30000000000000004  (WRONG!)
  Numeric: 0.10 + 0.20 = 0.30             (CORRECT!)

  Financial apps MUST use fixed-precision decimals.
  Float uses binary representation (1/3 can't be represented in binary exactly).
  Numeric/Decimal uses exact decimal representation.

  In Python: use decimal.Decimal, not float, for money calculations.
  In PostgreSQL: NUMERIC(precision, scale) stores exact decimal values.

Interview: "We use PostgreSQL NUMERIC(12,2) for monetary amounts, never FLOAT.
Float has rounding errors that accumulate in financial calculations.
NUMERIC stores exact decimal values. In Python, we use decimal.Decimal."
"""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import TimestampedModel, utcnow


class CategoryType(str, enum.Enum):
    """Whether this category is for expenses or income."""

    EXPENSE = "expense"
    INCOME = "income"
    BOTH = "both"  # e.g., "Transfer" can be income or expense


class RecurringFrequency(str, enum.Enum):
    """How often a recurring transaction repeats."""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class Category(TimestampedModel):
    """
    Expense/Income categories.

    Users can create custom categories (e.g., "Gym", "Netflix").
    We also provide default system categories (food, transport, etc.).

    System categories (is_default=True) are shared across all users.
    User categories (is_default=False) belong to one user.
    """

    __tablename__ = "categories"
    __table_args__ = (
        # Unique: a user can't have two categories with the same name
        # But two users CAN both have "Food" categories (scoped to user)
        Index("ix_categories_user_name", "user_id", "name"),
    )

    # NULL user_id = system/default category shared by all users
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Owner user. NULL = system default category",
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Category display name (e.g., Food, Transport, Salary)",
    )

    # Emoji or icon identifier (e.g., "🍕", "🚗", or "food-icon")
    icon: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Emoji or icon identifier for UI display",
    )

    # Hex color for UI (e.g., "#FF5733")
    color: Mapped[str | None] = mapped_column(
        String(7),
        nullable=True,
        comment="Hex color code for UI display (#RRGGBB)",
    )

    category_type: Mapped[CategoryType] = mapped_column(
        Enum(CategoryType, name="category_type"),
        default=CategoryType.EXPENSE,
        nullable=False,
        comment="Whether this category is for expenses, income, or both",
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True = system default category, shown to all users",
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    user: Mapped[User | None] = relationship(  # type: ignore[name-defined]
        "User",
        back_populates="categories",
    )

    expenses: Mapped[list[Expense]] = relationship(
        "Expense",
        back_populates="category",
        lazy="select",
    )

    incomes: Mapped[list[Income]] = relationship(
        "Income",
        back_populates="category",
        lazy="select",
    )

    budgets: Mapped[list[Budget]] = relationship(
        "Budget",
        back_populates="category",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name={self.name}, type={self.category_type})>"


class Expense(TimestampedModel):
    """
    Individual expense transaction.

    Core entity of the Finance Calculator.

    Key design choices:
    - amount: NUMERIC(12,2) — exact decimal, supports up to $9,999,999,999.99
    - tags: ARRAY(String) — PostgreSQL native array for flexible tagging
    - receipt_url: S3 URL in production, local path in dev
    - is_recurring: links to parent recurring expense
    """

    __tablename__ = "expenses"
    __table_args__ = (
        # Composite index: common query pattern is filter by user + date range
        Index("ix_expenses_user_date", "user_id", "date"),
        # Index for category queries per user
        Index("ix_expenses_user_category", "user_id", "category_id"),
    )

    # -------------------------------------------------------------------------
    # Core Fields
    # -------------------------------------------------------------------------
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owner of this expense",
    )

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,  # Allow uncategorized expenses
        index=True,
        comment="Expense category (nullable for uncategorized)",
    )

    # NUMERIC(12, 2) → up to 12 digits total, 2 decimal places
    # Max value: $9,999,999,999.99 (enough for any personal finance)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        comment="Expense amount in user's currency (exact decimal)",
    )

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="What was this expense for?",
    )

    date: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        comment="When the expense occurred (not when it was recorded)",
    )

    # -------------------------------------------------------------------------
    # Recurring Expense Fields
    # -------------------------------------------------------------------------
    is_recurring: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True = this expense recurs automatically",
    )

    recurring_frequency: Mapped[RecurringFrequency | None] = mapped_column(
        Enum(RecurringFrequency, name="recurring_frequency"),
        nullable=True,
        comment="How often this expense recurs (if is_recurring=True)",
    )

    recurring_end_date: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When to stop recurring (None = recur forever)",
    )

    # Self-referential: recurring instances point to their template
    parent_recurring_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expenses.id", ondelete="SET NULL"),
        nullable=True,
        comment="For generated recurring expenses: points to the template",
    )

    # -------------------------------------------------------------------------
    # Metadata Fields
    # -------------------------------------------------------------------------
    # PostgreSQL ARRAY type — stores list of strings natively
    # Better than a tags join table for simple tagging
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(50)),
        nullable=True,
        comment="Tags for categorization (e.g., ['business', 'reimbursable'])",
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Additional notes about this expense",
    )

    # URL to uploaded receipt image (S3 in production, local in dev)
    receipt_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="URL to receipt image (S3 URL in production)",
    )

    # Where was this expense made? (Optional location tracking)
    location: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Location where expense occurred",
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    user: Mapped[User] = relationship(  # type: ignore[name-defined]
        "User",
        back_populates="expenses",
    )

    category: Mapped[Category | None] = relationship(
        "Category",
        back_populates="expenses",
    )

    # Recurring children
    recurring_instances: Mapped[list[Expense]] = relationship(
        "Expense",
        foreign_keys=[parent_recurring_id],
        back_populates="parent_recurring",
        lazy="select",
    )

    parent_recurring: Mapped[Expense | None] = relationship(
        "Expense",
        foreign_keys=[parent_recurring_id],
        back_populates="recurring_instances",
        remote_side="Expense.id",
    )

    def __repr__(self) -> str:
        return f"<Expense(id={self.id}, amount={self.amount}, description={self.description[:30]!r})>"


class Income(TimestampedModel):
    """
    Income transaction.

    Similar to Expense but represents money coming IN.
    Tracks salary, freelance income, investment returns, etc.
    """

    __tablename__ = "income"
    __table_args__ = (Index("ix_income_user_date", "user_id", "date"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Income source (e.g., 'Employer Name', 'Freelance Client')",
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    date: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    is_recurring: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    recurring_frequency: Mapped[RecurringFrequency | None] = mapped_column(
        Enum(RecurringFrequency, name="recurring_frequency"),
        nullable=True,
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    user: Mapped[User] = relationship("User")  # type: ignore[name-defined]

    category: Mapped[Category | None] = relationship(
        "Category",
        back_populates="incomes",
    )

    def __repr__(self) -> str:
        return f"<Income(id={self.id}, amount={self.amount}, source={self.source!r})>"


class Budget(TimestampedModel):
    """
    Budget planning record.

    Defines how much a user plans to spend in a category per period.

    Example:
      Category: Food
      Amount: $500
      Period: 2026-05 (May 2026)
      Alert threshold: 80% (alert when 80% of budget is used)

    vs Expense:
      Budget = the PLAN (how much you WANT to spend)
      Expense = the REALITY (how much you DID spend)
      Analytics = Budget vs Actual comparison
    """

    __tablename__ = "budgets"
    __table_args__ = (
        # A user can only have one budget per category per month
        Index(
            "ix_budgets_user_category_period", "user_id", "category_id", "period_start"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        comment="Budget for this category. NULL = overall budget",
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        comment="Budget amount (how much is planned to spend)",
    )

    period_start: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Budget period start date (usually 1st of the month)",
    )

    period_end: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Budget period end date (usually last day of month)",
    )

    alert_threshold: Mapped[float] = mapped_column(
        default=0.80,
        nullable=False,
        comment="Alert when this % of budget is used (0.80 = 80%)",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    user: Mapped[User] = relationship("User", back_populates="budgets")  # type: ignore[name-defined]

    category: Mapped[Category | None] = relationship(
        "Category",
        back_populates="budgets",
    )

    def __repr__(self) -> str:
        return f"<Budget(id={self.id}, amount={self.amount}, period={self.period_start.date()})>"
