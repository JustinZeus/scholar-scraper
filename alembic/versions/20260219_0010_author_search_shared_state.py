"""Add shared author-search runtime and cache tables.

Revision ID: 20260219_0010
Revises: 20260219_0009
Create Date: 2026-02-19 22:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260219_0010"
down_revision: str | Sequence[str] | None = "20260219_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "author_search_runtime_state" not in table_names:
        op.create_table(
            "author_search_runtime_state",
            sa.Column("state_key", sa.String(length=64), nullable=False),
            sa.Column("last_live_request_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "consecutive_blocked_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "cooldown_rejection_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "cooldown_alert_emitted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
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
            sa.PrimaryKeyConstraint("state_key", name=op.f("pk_author_search_runtime_state")),
        )

    if "author_search_cache_entries" not in table_names:
        op.create_table(
            "author_search_cache_entries",
            sa.Column("query_key", sa.String(length=256), nullable=False),
            sa.Column(
                "payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "cached_at",
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
            sa.PrimaryKeyConstraint("query_key", name=op.f("pk_author_search_cache_entries")),
        )
        op.create_index(
            "ix_author_search_cache_expires_at",
            "author_search_cache_entries",
            ["expires_at"],
            unique=False,
        )
        op.create_index(
            "ix_author_search_cache_cached_at",
            "author_search_cache_entries",
            ["cached_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "author_search_cache_entries" in table_names:
        op.drop_index("ix_author_search_cache_cached_at", table_name="author_search_cache_entries")
        op.drop_index("ix_author_search_cache_expires_at", table_name="author_search_cache_entries")
        op.drop_table("author_search_cache_entries")

    if "author_search_runtime_state" in table_names:
        op.drop_table("author_search_runtime_state")
