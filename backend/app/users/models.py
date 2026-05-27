"""
User and UserProfile Database Models
======================================
Two tables instead of one:
  - users: Authentication data (email, password hash, role)
  - user_profiles: Personal data (name, currency preference, avatar)

Why split?
  1. Security: Most queries only need auth data (email, role)
     Separate table = don't load profile data when just checking JWT
  2. Flexibility: Profile can have many optional fields without
     making the users table bloated
  3. Principle of Single Responsibility

The separation follows Domain-Driven Design:
  User aggregate root → authentication and access control
  UserProfile → personal information and preferences
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import TimestampedModel


class UserRole(str, enum.Enum):
    """
    User roles for RBAC (Role-Based Access Control).

    RBAC Pattern:
      USER → Can only see/modify their own data
      ADMIN → Can see/modify all users' data
      SUPER_ADMIN → Can do anything, including deleting admins

    Why inherit from str?
      str enum → stored as strings in DB ("user", "admin") not integers (1, 2)
      More readable, no ID mapping needed, safe to add new roles
    """

    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class User(TimestampedModel):
    """
    User authentication table.

    Contains only authentication-critical data.
    Personal data lives in UserProfile.

    Indexes:
      - email: UNIQUE (login lookup)
      - username: UNIQUE (display name lookup)
      - is_active: WHERE clause filter (only serve active users)
    """

    __tablename__ = "users"

    # -------------------------------------------------------------------------
    # Authentication Fields
    # -------------------------------------------------------------------------
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,  # Unique index (one account per email)
        nullable=False,
        index=True,  # Fast lookup by email (used in every login)
        comment="User's email address (login identifier)",
    )

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Display username (shown in UI)",
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hashed password. NEVER store plaintext!",
    )

    # -------------------------------------------------------------------------
    # Authorization Fields
    # -------------------------------------------------------------------------
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.USER,
        nullable=False,
        comment="RBAC role: user | admin | super_admin",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="False = account suspended/deactivated",
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True = email address has been verified",
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    # profile: one-to-one relationship with UserProfile
    # cascade="all, delete-orphan" → deleting a User also deletes their profile
    profile: Mapped[UserProfile] = relationship(
        "UserProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,  # One-to-one: uselist=False means it's not a list
        lazy="select",  # Default: load on access (explicit)
    )

    expenses: Mapped[list[Expense]] = relationship(  # type: ignore[name-defined]
        "Expense",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    categories: Mapped[list[Category]] = relationship(  # type: ignore[name-defined]
        "Category",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    budgets: Mapped[list[Budget]] = relationship(  # type: ignore[name-defined]
        "Budget",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class UserProfile(TimestampedModel):
    """
    User profile and preferences table.

    One-to-one with User. Contains everything non-auth related.

    Why store currency preference?
      This is a finance app! Users in India use INR, users in US use USD.
      Every amount display respects their currency preference.
    """

    __tablename__ = "user_profiles"

    # -------------------------------------------------------------------------
    # Foreign Key to User
    # -------------------------------------------------------------------------
    # ondelete="CASCADE" → if User is deleted, profile is also deleted (DB-level)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,  # One profile per user (enforced at DB level too)
        nullable=False,
        comment="References the owner user",
    )

    # -------------------------------------------------------------------------
    # Personal Information
    # -------------------------------------------------------------------------
    first_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="User's first name",
    )

    last_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="User's last name",
    )

    avatar_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="URL to profile picture (S3 URL in production)",
    )

    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Short bio or description",
    )

    # -------------------------------------------------------------------------
    # Financial Preferences
    # -------------------------------------------------------------------------
    currency: Mapped[str] = mapped_column(
        String(3),  # ISO 4217 currency code (3 chars: USD, EUR, INR)
        default="USD",
        nullable=False,
        comment="Preferred currency (ISO 4217 code)",
    )

    timezone: Mapped[str] = mapped_column(
        String(50),
        default="UTC",
        nullable=False,
        comment="User's timezone (IANA timezone name e.g. America/New_York)",
    )

    # Default budget type preference
    monthly_budget_limit: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Monthly spending limit (None = no limit set)",
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    user: Mapped[User] = relationship(
        "User",
        back_populates="profile",
    )

    @property
    def full_name(self) -> str:
        """Computed property: first + last name."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or "Unknown"

    def __repr__(self) -> str:
        return f"<UserProfile(user_id={self.user_id}, name={self.full_name})>"
