"""
Expense and Category Service Layer
====================================
Business logic for categories and expenses.

Service Layer Responsibilities:
  - Query database (via SQLAlchemy)
  - Enforce business rules (ownership, limits, validation)
  - Raise domain exceptions (not HTTP exceptions — service doesn't know about HTTP)
  - Return domain objects (ORM models) — router converts to response schemas

Why the service doesn't raise HTTPException:
  Services are reusable from:
    - API endpoints (need HTTP errors)
    - Background jobs (need to log, not HTTP)
    - CLI tools (need to print, not HTTP)
  So services raise domain exceptions (NotFoundError, ForbiddenError, etc.)
  The router layer catches these and FastAPI converts them to HTTP responses.

N+1 Query Problem:
  N+1 happens when you load N expenses and then load each expense's category
  with a separate query — 1 + N queries total.

  Wrong: (N+1 queries)
    expenses = db.execute(select(Expense)).scalars().all()
    for expense in expenses:  # Each access triggers a DB query!
        print(expense.category.name)

  Right: (2 queries)
    expenses = db.execute(
        select(Expense).options(selectinload(Expense.category))
    ).scalars().all()
    # SQLAlchemy loads ALL categories in ONE extra query, then joins in Python

  selectinload vs joinedload:
    joinedload  → SQL JOIN (one query, wide result, duplicates for lists)
    selectinload → SELECT IN (two queries, clean, better for collections)

  Use selectinload for "has many" relationships.
  Use joinedload for "belongs to" single objects.

Interview: "We use selectinload to prevent N+1 queries on related objects.
When listing expenses, we load all categories in a single IN query rather
than a separate query per expense. The service layer raises domain exceptions
that the router layer catches and converts to HTTP responses."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import Text, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import Page, decode_cursor, encode_cursor
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.expenses.models import Category, CategoryType, Expense
from app.expenses.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ExpenseCreate,
    ExpenseFilters,
    ExpenseResponse,
    ExpenseUpdate,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# CATEGORY SERVICE
# =============================================================================


class CategoryService:
    """
    Business logic for category management.

    Categories come in two flavors:
      1. System defaults (user_id=None): visible to everyone, can't be modified
      2. User categories (user_id=owner): only visible to and modifiable by owner
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_categories(
        self,
        user_id: uuid.UUID,
        category_type: CategoryType | None = None,
    ) -> list[Category]:
        """
        Return system defaults + user's own categories (not deleted).

        SQL equivalent:
          SELECT * FROM categories
          WHERE deleted_at IS NULL
            AND (user_id IS NULL OR user_id = :user_id)
            AND (category_type = :type OR :type IS NULL)
          ORDER BY is_default DESC, name ASC
          -- system defaults first, then alphabetically

        The OR condition is key:
          user_id IS NULL → system default (everyone sees these)
          user_id = :user_id → user's own custom categories
        """
        stmt = (
            select(Category)
            .where(
                Category.deleted_at.is_(None),
                or_(
                    Category.user_id.is_(None),  # System defaults
                    Category.user_id == user_id,  # User's own
                ),
            )
            .order_by(
                Category.is_default.desc(),  # System defaults first
                Category.name.asc(),  # Then alphabetical
            )
        )

        if category_type:
            stmt = stmt.where(
                or_(
                    Category.category_type == category_type,
                    Category.category_type == CategoryType.BOTH,
                )
            )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_category(
        self,
        category_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Category:
        """
        Get a single category (must be system default OR owned by user).
        Raises NotFoundError if not accessible.
        """
        result = await self.db.execute(
            select(Category).where(
                Category.id == category_id,
                Category.deleted_at.is_(None),
                or_(
                    Category.user_id.is_(None),
                    Category.user_id == user_id,
                ),
            )
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundError(resource="Category", resource_id=str(category_id))
        return category

    async def create_category(
        self,
        user_id: uuid.UUID,
        data: CategoryCreate,
    ) -> Category:
        """
        Create a new user-owned category.

        Business rules:
          - User can't create a category with the same name as an existing one
            (case-insensitive: "Food" and "food" are the same)
          - System categories are seeded separately (can't be created via API)
        """
        # Check for name conflict (case-insensitive)
        existing = await self.db.execute(
            select(Category).where(
                Category.user_id == user_id,
                Category.deleted_at.is_(None),
                func.lower(Category.name) == data.name.lower(),
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictError(
                message=f"You already have a category named '{data.name}'",
                details={"name": data.name},
            )

        category = Category(
            user_id=user_id,
            name=data.name,
            icon=data.icon,
            color=data.color,
            category_type=data.category_type,
            is_default=False,  # User-created categories are never system defaults
        )
        self.db.add(category)
        await self.db.commit()
        await self.db.refresh(category)

        logger.info(
            "category_created",
            category_id=str(category.id),
            user_id=str(user_id),
            name=category.name,
        )
        return category

    async def update_category(
        self,
        category_id: uuid.UUID,
        user_id: uuid.UUID,
        data: CategoryUpdate,
    ) -> Category:
        """
        Update a category.

        Business rules:
          - Can only update your own categories (not system defaults)
          - System defaults (is_default=True) are immutable
        """
        result = await self.db.execute(
            select(Category).where(
                Category.id == category_id,
                Category.deleted_at.is_(None),
            )
        )
        category = result.scalar_one_or_none()

        if not category:
            raise NotFoundError(resource="Category", resource_id=str(category_id))

        # System defaults are read-only
        if category.is_default or category.user_id is None:
            raise ForbiddenError(message="System default categories cannot be modified")

        # Ownership check
        if category.user_id != user_id:
            raise ForbiddenError(message="You can only modify your own categories")

        # Apply only the fields that were actually sent (PATCH semantics)
        # model_dump(exclude_none=True) → only returns fields that are not None
        # e.g., if client only sent {"name": "Food"}, we only update name
        updates = data.model_dump(exclude_none=True)
        for field, value in updates.items():
            setattr(category, field, value)

        await self.db.commit()
        await self.db.refresh(category)

        logger.info(
            "category_updated",
            category_id=str(category_id),
            user_id=str(user_id),
            updates=list(updates.keys()),
        )
        return category

    async def delete_category(
        self,
        category_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Soft delete a category.

        Business rules:
          - Can only delete your own categories
          - System defaults cannot be deleted
          - Expenses using this category are NOT deleted; category_id is set to NULL
            (this is handled by the DB: ondelete="SET NULL" on the FK)
        """
        result = await self.db.execute(
            select(Category).where(
                Category.id == category_id,
                Category.deleted_at.is_(None),
            )
        )
        category = result.scalar_one_or_none()

        if not category:
            raise NotFoundError(resource="Category", resource_id=str(category_id))

        if category.is_default or category.user_id is None:
            raise ForbiddenError(message="System default categories cannot be deleted")

        if category.user_id != user_id:
            raise ForbiddenError(message="You can only delete your own categories")

        category.soft_delete()
        await self.db.commit()

        logger.info(
            "category_deleted",
            category_id=str(category_id),
            user_id=str(user_id),
        )


# =============================================================================
# EXPENSE SERVICE
# =============================================================================


class ExpenseService:
    """
    Business logic for expense CRUD operations.

    All methods enforce ownership: users can only read/modify their own expenses.
    This is the fundamental multi-tenancy requirement.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_expenses(
        self,
        user_id: uuid.UUID,
        filters: ExpenseFilters,
    ) -> Page[ExpenseResponse]:
        """
        List user's expenses with cursor pagination and optional filters.

        Cursor pagination flow:
          1. First request: no cursor → query most recent expenses
          2. Response includes next_cursor (if there are more pages)
          3. Client sends ?cursor=<next_cursor> for the next page
          4. We decode cursor → (last_date, last_id)
          5. WHERE clause: fetch only rows AFTER the cursor position

        Why fetch limit+1?
          We request one extra row. If we got it, there's a next page.
          We return only `limit` rows to the client and use the extra to
          determine has_next — no expensive COUNT query needed.

        SQL logic (conceptually):
          SELECT * FROM expenses
          WHERE user_id = :uid AND deleted_at IS NULL
            AND [cursor filter if provided]
            AND [optional: date range, category, amount, search]
          ORDER BY date DESC, id DESC
          LIMIT :limit + 1
        """
        # Build base query — always filter by user and active records
        stmt = (
            select(Expense)
            .where(
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
            )
            # selectinload: load all categories in ONE extra SQL query
            # Instead of: for each expense → SELECT category WHERE id=...  (N queries)
            # We do:       SELECT * FROM categories WHERE id IN (...)         (1 query)
            .options(selectinload(Expense.category))
            .order_by(Expense.date.desc(), Expense.id.desc())
        )

        # ── Apply optional filters ──────────────────────────────────────────

        if filters.from_date:
            stmt = stmt.where(Expense.date >= filters.from_date)

        if filters.to_date:
            stmt = stmt.where(Expense.date <= filters.to_date)

        if filters.category_id:
            stmt = stmt.where(Expense.category_id == filters.category_id)

        if filters.min_amount is not None:
            stmt = stmt.where(Expense.amount >= filters.min_amount)

        if filters.max_amount is not None:
            stmt = stmt.where(Expense.amount <= filters.max_amount)

        if filters.search:
            # ILIKE = case-insensitive LIKE
            # % wildcards: match anywhere in the string
            # "netflix" → matches "Monthly Netflix", "NETFLIX subscription", etc.
            stmt = stmt.where(Expense.description.ilike(f"%{filters.search}%"))

        if filters.is_recurring is not None:
            stmt = stmt.where(Expense.is_recurring == filters.is_recurring)

        # ── Apply cursor filter (pagination) ───────────────────────────────
        if filters.cursor:
            try:
                cursor_date, cursor_id = decode_cursor(filters.cursor)
                # We want everything "after" this point in (date DESC, id DESC) order
                # That means: date < cursor_date, OR date == cursor_date AND id < cursor_id
                stmt = stmt.where(
                    or_(
                        Expense.date < cursor_date,
                        and_(
                            Expense.date == cursor_date,
                            # Cast UUID to Text for consistent string comparison in PostgreSQL
                            Expense.id.cast(Text) < str(cursor_id),
                        ),
                    )
                )
            except ValueError:
                # Bad cursor → ignore it, start from the beginning
                logger.warning("invalid_expense_cursor", cursor=filters.cursor[:20])

        # ── Fetch limit+1 to detect next page ─────────────────────────────
        stmt = stmt.limit(filters.limit + 1)
        result = await self.db.execute(stmt)
        expenses = list(result.scalars().all())

        # Determine if there's a next page (we got the extra row)
        has_next = len(expenses) > filters.limit
        if has_next:
            expenses = expenses[: filters.limit]  # Drop the extra row

        # Build the cursor for the next page from the last item
        next_cursor: str | None = None
        if has_next and expenses:
            last = expenses[-1]
            next_cursor = encode_cursor(last.date, last.id)  # type: ignore[arg-type]

        # Convert ORM objects to response schemas
        items = [ExpenseResponse.model_validate(e) for e in expenses]

        return Page(
            items=items,
            has_next=has_next,
            next_cursor=next_cursor,
            limit=filters.limit,
        )

    async def get_expense(
        self,
        expense_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Expense:
        """
        Get a single expense by ID.

        Ownership check: user_id must match the expense's user_id.
        This prevents user A from reading user B's expenses by guessing UUIDs.

        We use selectinload here too — even for a single expense, we want the
        category loaded without triggering lazy loading (which fails in async).
        """
        result = await self.db.execute(
            select(Expense)
            .where(
                Expense.id == expense_id,
                Expense.user_id == user_id,  # ← ownership check
                Expense.deleted_at.is_(None),
            )
            .options(selectinload(Expense.category))
        )
        expense = result.scalar_one_or_none()

        if not expense:
            raise NotFoundError(resource="Expense", resource_id=str(expense_id))

        return expense

    async def create_expense(
        self,
        user_id: uuid.UUID,
        data: ExpenseCreate,
    ) -> Expense:
        """
        Create a new expense.

        If category_id is provided, verify it belongs to the user (or is a system default).
        This prevents user A from assigning user B's categories to their expense.
        """
        # Validate category ownership (if provided)
        if data.category_id:
            cat_result = await self.db.execute(
                select(Category).where(
                    Category.id == data.category_id,
                    Category.deleted_at.is_(None),
                    or_(
                        Category.user_id.is_(None),  # system default
                        Category.user_id == user_id,  # user's own
                    ),
                )
            )
            if not cat_result.scalar_one_or_none():
                raise NotFoundError(
                    resource="Category",
                    resource_id=str(data.category_id),
                )

        expense = Expense(
            user_id=user_id,
            amount=data.amount,
            description=data.description,
            date=data.date,
            category_id=data.category_id,
            tags=data.tags,
            notes=data.notes,
            location=data.location,
            is_recurring=data.is_recurring,
            recurring_frequency=data.recurring_frequency,
            recurring_end_date=data.recurring_end_date,
        )
        self.db.add(expense)
        await self.db.commit()

        # Reload with category relationship populated
        await self.db.refresh(expense)
        result = await self.db.execute(
            select(Expense)
            .where(Expense.id == expense.id)
            .options(selectinload(Expense.category))
        )
        expense = result.scalar_one()

        logger.info(
            "expense_created",
            expense_id=str(expense.id),
            user_id=str(user_id),
            amount=str(data.amount),
        )
        return expense

    async def update_expense(
        self,
        expense_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ExpenseUpdate,
    ) -> Expense:
        """
        Update an expense (PATCH semantics — only update provided fields).

        Key technique: model_dump(exclude_none=True)
          If client sends {"amount": 99.99}, updates = {"amount": Decimal("99.99")}
          We set only amount on the ORM object — description, date etc. unchanged.
          This is PATCH behavior (partial update), not PUT (full replace).
        """
        result = await self.db.execute(
            select(Expense)
            .where(
                Expense.id == expense_id,
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
            )
            .options(selectinload(Expense.category))
        )
        expense = result.scalar_one_or_none()

        if not expense:
            raise NotFoundError(resource="Expense", resource_id=str(expense_id))

        # Validate new category if provided
        if data.category_id is not None:
            cat_result = await self.db.execute(
                select(Category).where(
                    Category.id == data.category_id,
                    Category.deleted_at.is_(None),
                    or_(
                        Category.user_id.is_(None),
                        Category.user_id == user_id,
                    ),
                )
            )
            if not cat_result.scalar_one_or_none():
                raise NotFoundError(
                    resource="Category",
                    resource_id=str(data.category_id),
                )

        # Apply only provided fields
        updates = data.model_dump(exclude_none=True)
        for field, value in updates.items():
            setattr(expense, field, value)

        expense.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(expense)

        # Re-fetch with relationships
        result = await self.db.execute(
            select(Expense)
            .where(Expense.id == expense.id)
            .options(selectinload(Expense.category))
        )
        expense = result.scalar_one()

        logger.info(
            "expense_updated",
            expense_id=str(expense_id),
            user_id=str(user_id),
            updates=list(updates.keys()),
        )
        return expense

    async def delete_expense(
        self,
        expense_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Soft delete an expense.

        Sets deleted_at = NOW() instead of DELETE.
        The expense remains in the database for:
          - Audit trail
          - Undo functionality
          - Analytics (historical data, even if "deleted")
        """
        result = await self.db.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
            )
        )
        expense = result.scalar_one_or_none()

        if not expense:
            raise NotFoundError(resource="Expense", resource_id=str(expense_id))

        expense.soft_delete()
        await self.db.commit()

        logger.info(
            "expense_deleted",
            expense_id=str(expense_id),
            user_id=str(user_id),
        )

    async def get_summary(
        self,
        user_id: uuid.UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> dict[str, Decimal]:
        """
        Aggregate expense summary for a date range.

        Used by the analytics/dashboard endpoints.

        SQL equivalent:
          SELECT
            SUM(amount) as total,
            COUNT(*) as count,
            AVG(amount) as average
          FROM expenses
          WHERE user_id = :uid
            AND deleted_at IS NULL
            AND date BETWEEN :from AND :to
        """
        result = await self.db.execute(
            select(
                func.sum(Expense.amount).label("total"),
                func.count(Expense.id).label("count"),
                func.avg(Expense.amount).label("average"),
            ).where(
                Expense.user_id == user_id,
                Expense.deleted_at.is_(None),
                Expense.date >= from_date,
                Expense.date <= to_date,
            )
        )
        row = result.one()
        return {
            "total": Decimal(str(row.total or 0)),
            "count": int(row.count or 0),  # type: ignore[call-overload, truthy-function]
            "average": Decimal(str(row.average or 0)),
        }


# =============================================================================
# CATEGORY SEEDING
# =============================================================================


async def seed_default_categories(db: AsyncSession) -> None:
    """
    Seed system-wide default categories if they don't already exist.

    Called once at startup. Safe to call multiple times (idempotent):
    we check for existing records before inserting.

    These appear for all users automatically — they see both system categories
    and their own custom ones.
    """
    # Check if seeding has already happened
    result = await db.execute(
        select(func.count(Category.id)).where(Category.is_default.is_(True))
    )
    count = result.scalar_one()
    if count > 0:
        return  # Already seeded

    defaults = [
        # ── Expense categories ────────────────────────────────────────────
        ("Food & Dining", "🍕", "#FF6B6B", CategoryType.EXPENSE),
        ("Transportation", "🚗", "#4ECDC4", CategoryType.EXPENSE),
        ("Shopping", "🛍️", "#45B7D1", CategoryType.EXPENSE),
        ("Entertainment", "🎮", "#96CEB4", CategoryType.EXPENSE),
        ("Healthcare", "💊", "#FFEAA7", CategoryType.EXPENSE),
        ("Housing", "🏠", "#DDA0DD", CategoryType.EXPENSE),
        ("Education", "📚", "#98D8C8", CategoryType.EXPENSE),
        ("Personal Care", "💅", "#F7DC6F", CategoryType.EXPENSE),
        ("Travel", "✈️", "#82E0AA", CategoryType.EXPENSE),
        ("Utilities", "💡", "#AED6F1", CategoryType.EXPENSE),
        ("Subscriptions", "📱", "#F0B27A", CategoryType.EXPENSE),
        ("Gym & Fitness", "🏋️", "#A9CCE3", CategoryType.EXPENSE),
        ("Restaurants", "🍽️", "#F1948A", CategoryType.EXPENSE),
        ("Groceries", "🛒", "#82E0AA", CategoryType.EXPENSE),
        # ── Income categories ─────────────────────────────────────────────
        ("Salary", "💰", "#52BE80", CategoryType.INCOME),
        ("Freelance", "💻", "#5DADE2", CategoryType.INCOME),
        ("Investments", "📈", "#AF7AC5", CategoryType.INCOME),
        ("Rental Income", "🏘️", "#F0B27A", CategoryType.INCOME),
        ("Business", "💼", "#48C9B0", CategoryType.INCOME),
        ("Side Hustle", "⚡", "#F9E79F", CategoryType.INCOME),
        # ── Both ─────────────────────────────────────────────────────────
        ("Transfer", "🔄", "#BDC3C7", CategoryType.BOTH),
        ("Other", "📦", "#CCD1D1", CategoryType.BOTH),
    ]

    for name, icon, color, cat_type in defaults:
        db.add(
            Category(
                user_id=None,  # NULL = system default (no owner)
                name=name,
                icon=icon,
                color=color,
                category_type=cat_type,
                is_default=True,
            )
        )

    await db.commit()
    logger.info("default_categories_seeded", count=len(defaults))
