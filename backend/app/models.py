from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        CheckConstraint("status IN ('unreviewed', 'pending_review', 'approved', 'rejected')", name="status"),
        CheckConstraint("score >= 0 AND score < 'Infinity'::numeric", name="score"),
        CheckConstraint("youtube_channel_id ~ '^UC[A-Za-z0-9_-]{22}$'", name="youtube_id"),
        CheckConstraint("handle IS NULL OR (left(handle, 1) = '@' AND length(handle) > 1)", name="handle"),
        Index("ix_channels_handle_lower", func.lower(text("handle"))),
        Index("ix_channels_updated_at_id", "updated_at", "id"),
        Index("ix_channels_status_updated_at", "status", "updated_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    youtube_channel_id: Mapped[str] = mapped_column(String(24), unique=True)
    handle: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), server_default="unreviewed")
    score: Mapped[Decimal] = mapped_column(Numeric(12, 4), server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Install(Base):
    __tablename__ = "installs"
    __table_args__ = (CheckConstraint("reputation >= 0 AND reputation < 'Infinity'::numeric", name="reputation"),)
    # Client-generated anonymous installation UUID; not proof of a unique person.
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    reputation: Mapped[Decimal] = mapped_column(Numeric(12, 4), server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("install_id", "channel_id", name="uq_reports_install_channel"),
        CheckConstraint("length(btrim(reason)) BETWEEN 1 AND 2000", name="reason"),
        Index("ix_reports_channel_id_created_at", "channel_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    install_id: Mapped[UUID] = mapped_column(ForeignKey("installs.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Appeal(Base):
    __tablename__ = "appeals"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'accepted', 'rejected')", name="status"),
        CheckConstraint("length(btrim(reason)) BETWEEN 1 AND 2000", name="reason"),
        CheckConstraint("(status = 'open' AND resolved_at IS NULL) OR (status <> 'open' AND resolved_at IS NOT NULL)", name="resolution"),
        UniqueConstraint("id", "channel_id", name="uq_appeals_id_channel"),
        Index("ix_appeals_status_created_at", "status", "created_at"),
        Index("ix_appeals_channel_id", "channel_id"),
        Index("ix_appeals_install_id", "install_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    install_id: Mapped[UUID | None] = mapped_column(ForeignKey("installs.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModerationAction(Base):
    __tablename__ = "moderation_actions"
    # Composite FK prevents attaching an action to another channel's appeal.
    __table_args__ = (
        ForeignKeyConstraint(["appeal_id", "channel_id"], ["appeals.id", "appeals.channel_id"], ondelete="RESTRICT", name="fk_moderation_actions_appeal_channel"),
        CheckConstraint("action IN ('approve', 'reject', 'accept_appeal', 'reject_appeal')", name="action"),
        CheckConstraint("(action IN ('accept_appeal', 'reject_appeal') AND appeal_id IS NOT NULL) OR (action IN ('approve', 'reject') AND appeal_id IS NULL)", name="appeal_action"),
        CheckConstraint("length(btrim(reason)) BETWEEN 1 AND 2000", name="reason"),
        CheckConstraint("length(btrim(actor)) > 0", name="actor"),
        Index("ix_moderation_actions_channel_id_created_at", "channel_id", "created_at"),
        Index("ix_moderation_actions_appeal_id", "appeal_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    appeal_id: Mapped[UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(100))  # Admin label, never an API key.
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
