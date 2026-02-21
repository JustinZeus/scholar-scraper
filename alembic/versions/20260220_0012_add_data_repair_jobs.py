"""Add data repair job audit table.

Revision ID: 20260220_0012
Revises: 20260220_0011
Create Date: 2026-02-20 23:35:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260220_0012"
down_revision: str | Sequence[str] | None = "20260220_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _create_data_repair_jobs_table() -> None:
    op.create_table(
        "data_repair_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('planned', 'running', 'completed', 'failed')",
            name="data_repair_jobs_status_valid",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_repair_jobs")),
    )


def _create_data_repair_jobs_indexes() -> None:
    op.create_index(
        "ix_data_repair_jobs_created_at",
        "data_repair_jobs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_data_repair_jobs_job_name_created_at",
        "data_repair_jobs",
        ["job_name", "created_at"],
        unique=False,
    )


def _drop_data_repair_jobs_indexes() -> None:
    op.drop_index("ix_data_repair_jobs_job_name_created_at", table_name="data_repair_jobs")
    op.drop_index("ix_data_repair_jobs_created_at", table_name="data_repair_jobs")


def upgrade() -> None:
    if "data_repair_jobs" in _table_names():
        return
    _create_data_repair_jobs_table()
    _create_data_repair_jobs_indexes()


def downgrade() -> None:
    if "data_repair_jobs" not in _table_names():
        return
    _drop_data_repair_jobs_indexes()
    op.drop_table("data_repair_jobs")
