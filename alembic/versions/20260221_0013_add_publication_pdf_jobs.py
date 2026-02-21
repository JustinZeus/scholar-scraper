"""Add persistent publication PDF job tracking tables.

Revision ID: 20260221_0013
Revises: 20260220_0012
Create Date: 2026-02-21 12:25:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260221_0013"
down_revision: str | Sequence[str] | None = "20260220_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _create_publication_pdf_jobs_table() -> None:
    op.create_table(
        "publication_pdf_jobs",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_reason", sa.String(length=64), nullable=True),
        sa.Column("last_failure_detail", sa.Text(), nullable=True),
        sa.Column("last_source", sa.String(length=32), nullable=True),
        sa.Column("last_requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'resolved', 'failed')",
            name="publication_pdf_jobs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["last_requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("publication_id", name=op.f("pk_publication_pdf_jobs")),
    )


def _create_publication_pdf_jobs_indexes() -> None:
    op.create_index(
        "ix_publication_pdf_jobs_status",
        "publication_pdf_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_publication_pdf_jobs_updated_at",
        "publication_pdf_jobs",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_publication_pdf_jobs_queued_at",
        "publication_pdf_jobs",
        ["queued_at"],
        unique=False,
    )


def _create_publication_pdf_job_events_table() -> None:
    op.create_table(
        "publication_pdf_job_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_pdf_job_events")),
    )


def _create_publication_pdf_job_events_indexes() -> None:
    op.create_index(
        "ix_publication_pdf_job_events_publication_created",
        "publication_pdf_job_events",
        ["publication_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_publication_pdf_job_events_created_at",
        "publication_pdf_job_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_publication_pdf_job_events_event_type",
        "publication_pdf_job_events",
        ["event_type"],
        unique=False,
    )


def _drop_publication_pdf_jobs_indexes() -> None:
    op.drop_index("ix_publication_pdf_jobs_queued_at", table_name="publication_pdf_jobs")
    op.drop_index("ix_publication_pdf_jobs_updated_at", table_name="publication_pdf_jobs")
    op.drop_index("ix_publication_pdf_jobs_status", table_name="publication_pdf_jobs")


def _drop_publication_pdf_job_events_indexes() -> None:
    op.drop_index("ix_publication_pdf_job_events_event_type", table_name="publication_pdf_job_events")
    op.drop_index("ix_publication_pdf_job_events_created_at", table_name="publication_pdf_job_events")
    op.drop_index(
        "ix_publication_pdf_job_events_publication_created",
        table_name="publication_pdf_job_events",
    )


def upgrade() -> None:
    tables = _table_names()
    if "publication_pdf_jobs" not in tables:
        _create_publication_pdf_jobs_table()
        _create_publication_pdf_jobs_indexes()
    if "publication_pdf_job_events" not in tables:
        _create_publication_pdf_job_events_table()
        _create_publication_pdf_job_events_indexes()


def downgrade() -> None:
    tables = _table_names()
    if "publication_pdf_job_events" in tables:
        _drop_publication_pdf_job_events_indexes()
        op.drop_table("publication_pdf_job_events")
    if "publication_pdf_jobs" in tables:
        _drop_publication_pdf_jobs_indexes()
        op.drop_table("publication_pdf_jobs")
