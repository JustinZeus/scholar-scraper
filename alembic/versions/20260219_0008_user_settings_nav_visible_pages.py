"""Add per-user nav visibility settings.

Revision ID: 20260219_0008
Revises: 20260217_0007
Create Date: 2026-02-19 14:58:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260219_0008"
down_revision: str | Sequence[str] | None = "20260217_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "user_settings"
DEFAULT_NAV_VISIBLE_PAGES_SQL = (
    "'[\"dashboard\",\"scholars\",\"publications\",\"settings\",\"style-guide\",\"runs\",\"users\"]'::jsonb"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "nav_visible_pages" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "nav_visible_pages",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text(DEFAULT_NAV_VISIBLE_PAGES_SQL),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "nav_visible_pages" in columns:
        op.drop_column(TABLE_NAME, "nav_visible_pages")
