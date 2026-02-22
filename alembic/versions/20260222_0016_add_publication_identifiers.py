"""Add publication identifiers table.

Revision ID: 20260222_0016
Revises: 20260221_0015
Create Date: 2026-02-22 12:45:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260222_0016"
down_revision: str | Sequence[str] | None = "20260221_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _create_publication_identifiers_table() -> None:
    op.create_table(
        "publication_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.Column("value_normalized", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "confidence_score",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("evidence_url", sa.Text(), nullable=True),
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
            "confidence_score >= 0 AND confidence_score <= 1",
            name="publication_identifiers_confidence_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_identifiers")),
        sa.UniqueConstraint(
            "publication_id",
            "kind",
            "value_normalized",
            name="uq_publication_identifiers_publication_kind_value",
        ),
    )


def _create_publication_identifiers_indexes() -> None:
    op.create_index(
        "ix_publication_identifiers_kind_value",
        "publication_identifiers",
        ["kind", "value_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_publication_identifiers_publication_id",
        "publication_identifiers",
        ["publication_id"],
        unique=False,
    )


def _drop_publication_identifiers_indexes() -> None:
    op.drop_index("ix_publication_identifiers_publication_id", table_name="publication_identifiers")
    op.drop_index("ix_publication_identifiers_kind_value", table_name="publication_identifiers")


def upgrade() -> None:
    if "publication_identifiers" in _table_names():
        return
    _create_publication_identifiers_table()
    _create_publication_identifiers_indexes()


def downgrade() -> None:
    if "publication_identifiers" not in _table_names():
        return
    _drop_publication_identifiers_indexes()
    op.drop_table("publication_identifiers")
