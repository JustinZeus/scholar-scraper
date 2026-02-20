"""Add DOI column to publications.

Revision ID: 20260220_0011
Revises: 20260219_0010
Create Date: 2026-02-20 13:35:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260220_0011"
down_revision: str | Sequence[str] | None = "20260219_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    for column in inspector.get_columns(table_name):
        if str(column.get("name")) == column_name:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "publications" not in table_names:
        return
    if not _has_column(inspector, "publications", "doi"):
        op.add_column("publications", sa.Column("doi", sa.String(length=255), nullable=True))
    index_names = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_doi" not in index_names:
        op.create_index("ix_publications_doi", "publications", ["doi"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "publications" not in table_names:
        return
    index_names = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_doi" in index_names:
        op.drop_index("ix_publications_doi", table_name="publications")
    if _has_column(inspector, "publications", "doi"):
        op.drop_column("publications", "doi")
