"""
Base Database Model
====================
All database models inherit from this TimestampedModel which provides:
  - id: UUID primary key (better than integer — see below)
  - created_at: When the record was created
  - updated_at: When the record was last modified
  - deleted_at: For soft delete (see below)

Why UUID primary keys instead of auto-increment integers?
  Integer IDs:
    - Sequential: user_id=1, 2, 3 → attackers know you have 3 users
    - Predictable: /users/4 → try /users/5, /users/6 (enumeration attacks)
    - Single-database: IDs collide when merging databases (microservices)

  UUID IDs:
    - Random: user_id=550e8400-e29b-41d4-a716-446655440000
    - Unpredictable: can't enumerate resources
    - Global: no collisions even across databases
    - Industry standard: Stripe, GitHub, AWS all use UUIDs

Soft Delete Pattern:
  Instead of DELETE FROM expenses WHERE id=123 (permanent, unrecoverable),
  we set deleted_at = NOW() and filter it in queries.

  Benefits:
  - Audit trail: can see deleted records
  - Recoverable: can undelete (undo feature!)
  - Referential integrity: foreign keys still valid
  - GDPR: you CAN hard delete when legally required (scheduled job)

  Example:
    User accidentally deletes an expense → they can undo it
    Admin audit: "Show me all deleted expenses from last month"

Interview: "We use soft delete with a deleted_at timestamp. Active records
have deleted_at=null, deleted records have the deletion timestamp. We add
WHERE deleted_at IS NULL to all queries via a SQLAlchemy query extension."
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    """Get current UTC time. Always timezone-aware."""
    return datetime.now(UTC)


class TimestampedModel(Base):
    """
    Abstract base model with UUID primary key and timestamps.

    'abstract = True' means this class has no database table of its own.
    It's like an interface/mixin in other languages.
    All fields defined here appear in EVERY model that inherits from it.
    """

    __abstract__ = True  # No table for this class itself

    # -------------------------------------------------------------------------
    # Primary Key: UUID
    # -------------------------------------------------------------------------
    # gen_random_uuid() → PostgreSQL function to generate UUID server-side
    # default=uuid.uuid4 → Python fallback if server default not available
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="Unique identifier (UUID v4)",
    )

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    # server_default=func.now() → PostgreSQL sets this on INSERT
    # onupdate=func.now() → PostgreSQL updates this on UPDATE
    # timezone=True → always store with timezone info (UTC)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
        comment="When this record was created",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="When this record was last updated",
    )

    # -------------------------------------------------------------------------
    # Soft Delete
    # -------------------------------------------------------------------------
    # NULL = not deleted (active record)
    # timestamp = when it was deleted
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,  # Index because we filter on this constantly
        comment="Soft delete timestamp. NULL means active.",
    )

    @property
    def is_deleted(self) -> bool:
        """True if this record has been soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted without removing from database."""
        self.deleted_at = utcnow()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary (useful for caching/logging)."""
        return {col.name: getattr(self, col.name) for col in self.__table__.columns}

    def __repr__(self) -> str:
        """Developer-friendly string representation."""
        return f"<{self.__class__.__name__}(id={self.id})>"
