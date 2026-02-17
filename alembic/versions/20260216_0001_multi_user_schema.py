"""Create multi-user core schema

Revision ID: 20260216_0001
Revises:
Create Date: 2026-02-16 17:10:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260216_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


run_status_enum = sa.Enum(
    "running",
    "success",
    "partial_failure",
    "failed",
    name="run_status",
)
run_trigger_type_enum = sa.Enum(
    "manual",
    "scheduled",
    name="run_trigger_type",
)
run_status_ref = postgresql.ENUM(
    "running",
    "success",
    "partial_failure",
    "failed",
    name="run_status",
    create_type=False,
)
run_trigger_type_ref = postgresql.ENUM(
    "manual",
    "scheduled",
    name="run_trigger_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    run_status_enum.create(bind, checkfirst=True)
    run_trigger_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "auto_run_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "run_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1440"),
        ),
        sa.Column(
            "request_delay_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
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
        sa.CheckConstraint(
            "run_interval_minutes >= 15",
            name="ck_user_settings_run_interval_minutes_min_15",
        ),
        sa.CheckConstraint(
            "request_delay_seconds >= 1",
            name="ck_user_settings_request_delay_seconds_min_1",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_settings_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_settings"),
    )

    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.String(length=64), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("title_raw", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column(
            "citation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("author_text", sa.Text(), nullable=True),
        sa.Column("venue_text", sa.Text(), nullable=True),
        sa.Column("pub_url", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_publications"),
        sa.UniqueConstraint(
            "fingerprint_sha256",
            name="uq_publications_fingerprint",
        ),
    )
    op.create_index(
        "uq_publications_cluster_id_not_null",
        "publications",
        ["cluster_id"],
        unique=True,
        postgresql_where=sa.text("cluster_id IS NOT NULL"),
    )

    op.create_table(
        "scholar_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scholar_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "baseline_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_run_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", run_status_ref, nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_scholar_profiles_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scholar_profiles"),
        sa.UniqueConstraint(
            "user_id",
            "scholar_id",
            name="uq_scholar_profiles_user_scholar",
        ),
    )
    op.create_index(
        "ix_scholar_profiles_user_enabled",
        "scholar_profiles",
        ["user_id", "is_enabled"],
        unique=False,
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", run_trigger_type_ref, nullable=False),
        sa.Column("status", run_status_ref, nullable=False),
        sa.Column(
            "start_dt",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("end_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scholar_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "new_pub_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "error_log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_crawl_runs_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_runs"),
    )
    op.create_index(
        "ix_crawl_runs_user_start",
        "crawl_runs",
        ["user_id", "start_dt"],
        unique=False,
    )

    op.create_table(
        "scholar_publications",
        sa.Column("scholar_profile_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("first_seen_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["first_seen_run_id"],
            ["crawl_runs.id"],
            name="fk_scholar_publications_first_seen_run_id_crawl_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name="fk_scholar_publications_publication_id_publications",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scholar_profile_id"],
            ["scholar_profiles.id"],
            name="fk_scholar_publications_scholar_profile_id_scholar_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "scholar_profile_id",
            "publication_id",
            name="pk_scholar_publications",
        ),
    )
    op.create_index(
        "ix_scholar_publications_is_read",
        "scholar_publications",
        ["is_read"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scholar_publications_is_read", table_name="scholar_publications")
    op.drop_table("scholar_publications")

    op.drop_index("ix_crawl_runs_user_start", table_name="crawl_runs")
    op.drop_table("crawl_runs")

    op.drop_index("ix_scholar_profiles_user_enabled", table_name="scholar_profiles")
    op.drop_table("scholar_profiles")

    op.drop_index("uq_publications_cluster_id_not_null", table_name="publications")
    op.drop_table("publications")

    op.drop_table("user_settings")
    op.drop_table("users")

    bind = op.get_bind()
    run_trigger_type_enum.drop(bind, checkfirst=True)
    run_status_enum.drop(bind, checkfirst=True)
