"""Add scrape safety state fields to user settings.

Revision ID: 20260219_0009
Revises: 20260219_0008
Create Date: 2026-02-19 21:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260219_0009"
down_revision: str | Sequence[str] | None = "20260219_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "user_settings"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "scrape_safety_state" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "scrape_safety_state",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

    if "scrape_cooldown_until" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("scrape_cooldown_until", sa.DateTime(timezone=True), nullable=True),
        )

    if "scrape_cooldown_reason" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("scrape_cooldown_reason", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "scrape_cooldown_reason" in columns:
        op.drop_column(TABLE_NAME, "scrape_cooldown_reason")

    if "scrape_cooldown_until" in columns:
        op.drop_column(TABLE_NAME, "scrape_cooldown_until")

    if "scrape_safety_state" in columns:
        op.drop_column(TABLE_NAME, "scrape_safety_state")
