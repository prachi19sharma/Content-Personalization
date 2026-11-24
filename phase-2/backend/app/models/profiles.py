"""Three levels of personalization profile.

    GlobalProfile  — one per user, applies everywhere
    DomainProfile  — one per (user, domain): board + class, brand + audience, …
    AgentProfile   — one per (user, agent_key): the narrow specifics of one job

An agent's context is assembled from all three, most general first.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.database.types import JSONBType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class GlobalProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Profile information shared by every domain and agent."""

    __tablename__ = "global_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occupation: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    language: Mapped[str] = mapped_column(String(64), default="English", nullable=False)

    # "concise" | "balanced" | "detailed"
    preferred_response_length: Mapped[str] = mapped_column(
        String(32), default="balanced", nullable=False
    )
    # "friendly" | "professional" | "direct" | "casual" | "academic"
    communication_style: Mapped[str] = mapped_column(
        String(32), default="friendly", nullable=False
    )
    general_skill_level: Mapped[str] = mapped_column(
        String(32), default="intermediate", nullable=False
    )

    interests: Mapped[list[str]] = mapped_column(JSONBType, default=list, nullable=False)
    goals: Mapped[list[str]] = mapped_column(JSONBType, default=list, nullable=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    personalization_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    user: Mapped[User] = relationship(back_populates="global_profile")

    def to_context_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "occupation": self.occupation,
            "location": self.location,
            "language": self.language,
            "preferred_response_length": self.preferred_response_length,
            "communication_style": self.communication_style,
            "general_skill_level": self.general_skill_level,
            "interests": list(self.interests or []),
            "goals": list(self.goals or []),
            "preferences": dict(self.preferences or {}),
            "bio": self.bio,
        }


class DomainProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One brand inside one domain: the answers every agent in it shares.

    A user may hold **many** of these per domain -- one per brand or client --
    so the same agent can be configured separately for each. The original build
    had ``UNIQUE(user_id, domain)``, which allowed exactly one brand per account
    and forced a user to overwrite it to work on a second client.

    Exactly one row per ``(user_id, domain)`` carries ``is_active``; that is the
    brand the app is currently working in. Keeping the marker here rather than
    as ``users.active_brand_id`` avoids a circular foreign key between the two
    tables, and means deleting a brand can never leave a dangling pointer.
    """

    __tablename__ = "domain_profiles"
    __table_args__ = (
        # "which brand is this account working in" is read on every request.
        Index("ix_domain_profiles_user_active", "user_id", "is_active"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Catalog domain key, e.g. ``education``.
    domain: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    #: Human label for the brand, shown in the switcher. Defaults to the
    #: ``brand_name`` answer but kept separate: renaming the brand in the
    #: profile should not silently repoint every child row.
    label: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    #: The brand this account is currently working in, one per user+domain.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    profile_data: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict, nullable=False)
    is_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    user: Mapped[User] = relationship(back_populates="domain_profiles")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DomainProfile {self.domain}/{self.label!r} user={self.user_id}>"


class AgentProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The narrow specifics for one agent, e.g. weak chapters for Class 10 Maths."""

    __tablename__ = "agent_profiles"
    __table_args__ = (
        # Per brand, not per account: the same agent holds a separate
        # configuration for every brand the user works on.
        UniqueConstraint(
            "user_id", "brand_profile_id", "agent_key", name="uq_agent_profiles_user_brand_agent"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: The brand these answers belong to. Nullable only so the migration can
    #: backfill; every row written by the application carries one.
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("domain_profiles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    #: Fully qualified catalog key, e.g. ``education.class10-maths``.
    agent_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    #: Denormalised for cheap per-domain queries.
    domain: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    profile_data: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict, nullable=False)
    is_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="agent_profiles")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentProfile {self.agent_key} user={self.user_id}>"
