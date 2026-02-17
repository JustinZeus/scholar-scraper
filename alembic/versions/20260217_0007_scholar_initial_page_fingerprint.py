"""Add per-scholar initial page fingerprint snapshot columns.

Revision ID: 20260217_0007
Revises: 20260217_0006
Create Date: 2026-02-17 18:55:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0007"
down_revision: str | Sequence[str] | None = "20260217_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "scholar_profiles"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "last_initial_page_fingerprint_sha256" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("last_initial_page_fingerprint_sha256", sa.String(length=64), nullable=True),
        )

    if "last_initial_page_checked_at" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("last_initial_page_checked_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "last_initial_page_checked_at" in columns:
        op.drop_column(TABLE_NAME, "last_initial_page_checked_at")

    if "last_initial_page_fingerprint_sha256" in columns:
        op.drop_column(TABLE_NAME, "last_initial_page_fingerprint_sha256")
