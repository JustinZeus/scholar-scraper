from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunTriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class QueueItemStatus(StrEnum):
    QUEUED = "queued"
    RETRYING = "retrying"
    DROPPED = "dropped"


RUN_STATUS_DB_ENUM = Enum(
    RunStatus,
    name="run_status",
    values_callable=lambda members: [member.value for member in members],
)
RUN_TRIGGER_TYPE_DB_ENUM = Enum(
    RunTriggerType,
    name="run_trigger_type",
    values_callable=lambda members: [member.value for member in members],
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserSetting(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint(
            "run_interval_minutes >= 15",
            name="run_interval_minutes_min_15",
        ),
        CheckConstraint(
            "request_delay_seconds >= 1",
            name="request_delay_seconds_min_1",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    auto_run_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    run_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1440")
    )
    request_delay_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScholarProfile(Base):
    __tablename__ = "scholar_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "scholar_id", name="uq_scholar_profiles_user_scholar"),
        Index("ix_scholar_profiles_user_enabled", "user_id", "is_enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scholar_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_image_url: Mapped[str | None] = mapped_column(Text)
    profile_image_override_url: Mapped[str | None] = mapped_column(Text)
    profile_image_upload_path: Mapped[str | None] = mapped_column(Text)
    last_initial_page_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64))
    last_initial_page_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    baseline_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_run_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[RunStatus | None] = mapped_column(
        RUN_STATUS_DB_ENUM,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        Index("ix_crawl_runs_user_start", "user_id", "start_dt"),
        Index(
            "uq_crawl_runs_user_manual_idempotency_key",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text(
                "idempotency_key IS NOT NULL AND trigger_type = 'manual'::run_trigger_type"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    trigger_type: Mapped[RunTriggerType] = mapped_column(
        RUN_TRIGGER_TYPE_DB_ENUM, nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        RUN_STATUS_DB_ENUM, nullable=False
    )
    start_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    end_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scholar_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    new_pub_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    error_log: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("fingerprint_sha256", name="uq_publications_fingerprint"),
        Index(
            "uq_publications_cluster_id_not_null",
            "cluster_id",
            unique=True,
            postgresql_where=text("cluster_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str | None] = mapped_column(String(64))
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title_raw: Mapped[str] = mapped_column(Text, nullable=False)
    title_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    citation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    author_text: Mapped[str | None] = mapped_column(Text)
    venue_text: Mapped[str | None] = mapped_column(Text)
    pub_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScholarPublication(Base):
    __tablename__ = "scholar_publications"
    __table_args__ = (
        Index("ix_scholar_publications_is_read", "is_read"),
    )

    scholar_profile_id: Mapped[int] = mapped_column(
        ForeignKey("scholar_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    first_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionQueueItem(Base):
    __tablename__ = "ingestion_queue_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "scholar_profile_id",
            name="uq_ingestion_queue_user_scholar",
        ),
        CheckConstraint(
            "status IN ('queued', 'retrying', 'dropped')",
            name="ingestion_queue_status_valid",
        ),
        Index("ix_ingestion_queue_next_attempt", "next_attempt_dt"),
        Index("ix_ingestion_queue_status_next_attempt", "status", "next_attempt_dt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scholar_profile_id: Mapped[int] = mapped_column(
        ForeignKey("scholar_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    resume_cstart: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'queued'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_attempt_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="SET NULL"),
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    dropped_reason: Mapped[str | None] = mapped_column(String(128))
    dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
