"""Add database-backed manual run idempotency key

Revision ID: 20260217_0005
Revises: 20260217_0004
Create Date: 2026-02-17 16:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0005"
down_revision: str | Sequence[str] | None = "20260217_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "uq_crawl_runs_user_manual_idempotency_key"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("crawl_runs")}
    indexes = {index["name"] for index in inspector.get_indexes("crawl_runs")}

    if "idempotency_key" not in columns:
        op.add_column(
            "crawl_runs",
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        )
        columns.add("idempotency_key")

    if "idempotency_key" in columns:
        op.execute(
            """
            UPDATE crawl_runs
            SET idempotency_key = NULLIF(BTRIM(error_log #>> '{meta,idempotency_key}'), '')
            WHERE trigger_type = 'manual'
              AND idempotency_key IS NULL
            """
        )
        # Preserve one winning row per (user_id, idempotency_key) before creating uniqueness.
        op.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, idempotency_key
                        ORDER BY start_dt DESC, id DESC
                    ) AS rn
                FROM crawl_runs
                WHERE trigger_type = 'manual'
                  AND idempotency_key IS NOT NULL
            )
            UPDATE crawl_runs AS runs
            SET idempotency_key = NULL
            FROM ranked
            WHERE runs.id = ranked.id
              AND ranked.rn > 1
            """
        )

    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            "crawl_runs",
            ["user_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text(
                "idempotency_key IS NOT NULL AND trigger_type = 'manual'::run_trigger_type"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("crawl_runs")}
    indexes = {index["name"] for index in inspector.get_indexes("crawl_runs")}

    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="crawl_runs")
    if "idempotency_key" in columns:
        op.drop_column("crawl_runs", "idempotency_key")
