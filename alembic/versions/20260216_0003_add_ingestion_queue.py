"""Add ingestion continuation queue table

Revision ID: 20260216_0003
Revises: 20260216_0002
Create Date: 2026-02-16 23:45:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260216_0003"
down_revision: str | Sequence[str] | None = "20260216_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_queue_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scholar_profile_id", sa.Integer(), nullable=False),
        sa.Column(
            "resume_cstart",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "next_attempt_dt",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_run_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["crawl_runs.id"],
            name="fk_ingestion_queue_items_last_run_id_crawl_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scholar_profile_id"],
            ["scholar_profiles.id"],
            name="fk_ingestion_queue_items_scholar_profile_id_scholar_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ingestion_queue_items_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_queue_items"),
        sa.UniqueConstraint(
            "user_id",
            "scholar_profile_id",
            name="uq_ingestion_queue_user_scholar",
        ),
    )
    op.create_index(
        "ix_ingestion_queue_next_attempt",
        "ingestion_queue_items",
        ["next_attempt_dt"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_queue_next_attempt", table_name="ingestion_queue_items")
    op.drop_table("ingestion_queue_items")
