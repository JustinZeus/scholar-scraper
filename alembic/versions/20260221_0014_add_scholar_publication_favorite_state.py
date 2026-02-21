"""add scholar publication favorite state

Revision ID: 20260221_0014
Revises: 20260221_0013
Create Date: 2026-02-21 14:35:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260221_0014"
down_revision = "20260221_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scholar_publications",
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_scholar_publications_is_favorite",
        "scholar_publications",
        ["is_favorite"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scholar_publications_is_favorite",
        table_name="scholar_publications",
    )
    op.drop_column("scholar_publications", "is_favorite")
