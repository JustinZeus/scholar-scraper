"""Add scholar profile image metadata and overrides.

Revision ID: 20260217_0006
Revises: 20260217_0005
Create Date: 2026-02-17 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0006"
down_revision: str | Sequence[str] | None = "20260217_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "scholar_profiles"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "profile_image_url" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("profile_image_url", sa.Text(), nullable=True),
        )

    if "profile_image_override_url" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("profile_image_override_url", sa.Text(), nullable=True),
        )

    if "profile_image_upload_path" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("profile_image_upload_path", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

    if "profile_image_upload_path" in columns:
        op.drop_column(TABLE_NAME, "profile_image_upload_path")

    if "profile_image_override_url" in columns:
        op.drop_column(TABLE_NAME, "profile_image_override_url")

    if "profile_image_url" in columns:
        op.drop_column(TABLE_NAME, "profile_image_url")
