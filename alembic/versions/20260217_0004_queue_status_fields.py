"""Add queue status and dropped diagnostics fields

Revision ID: 20260217_0004
Revises: 20260216_0003
Create Date: 2026-02-17 10:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0004"
down_revision: str | Sequence[str] | None = "20260216_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ingestion_queue_items")}
    indexes = {index["name"] for index in inspector.get_indexes("ingestion_queue_items")}
    checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("ingestion_queue_items")
    }

    if "status" not in columns:
        op.add_column(
            "ingestion_queue_items",
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'queued'"),
            ),
        )
        columns.add("status")

    if "dropped_reason" not in columns:
        op.add_column(
            "ingestion_queue_items",
            sa.Column("dropped_reason", sa.String(length=128), nullable=True),
        )

    if "dropped_at" not in columns:
        op.add_column(
            "ingestion_queue_items",
            sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "status" in columns:
        op.execute(
            """
            UPDATE ingestion_queue_items
            SET status = 'queued'
            WHERE status IS NULL OR status = ''
            """
        )

    if "ingestion_queue_status_valid" not in checks:
        op.create_check_constraint(
            "ingestion_queue_status_valid",
            "ingestion_queue_items",
            "status IN ('queued', 'retrying', 'dropped')",
        )

    if "ix_ingestion_queue_status_next_attempt" not in indexes:
        op.create_index(
            "ix_ingestion_queue_status_next_attempt",
            "ingestion_queue_items",
            ["status", "next_attempt_dt"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ingestion_queue_items")}
    indexes = {index["name"] for index in inspector.get_indexes("ingestion_queue_items")}
    checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("ingestion_queue_items")
    }

    if "ix_ingestion_queue_status_next_attempt" in indexes:
        op.drop_index("ix_ingestion_queue_status_next_attempt", table_name="ingestion_queue_items")
    if "ingestion_queue_status_valid" in checks:
        op.drop_constraint("ingestion_queue_status_valid", "ingestion_queue_items", type_="check")
    if "dropped_at" in columns:
        op.drop_column("ingestion_queue_items", "dropped_at")
    if "dropped_reason" in columns:
        op.drop_column("ingestion_queue_items", "dropped_reason")
    if "status" in columns:
        op.drop_column("ingestion_queue_items", "status")
