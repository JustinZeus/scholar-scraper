import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "user_settings",
    "scholar_profiles",
    "publications",
    "scholar_publications",
    "crawl_runs",
    "ingestion_queue_items",
}

EXPECTED_ENUMS = {"run_status", "run_trigger_type"}
EXPECTED_REVISION = "20260217_0007"


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_migration_creates_expected_tables(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    table_names = {row[0] for row in result}
    assert EXPECTED_TABLES.issubset(table_names)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_migration_registers_expected_enums(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT t.typname
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
            """
        )
    )
    enum_names = {row[0] for row in result}
    assert EXPECTED_ENUMS.issubset(enum_names)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_migration_head_revision_is_applied(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT version_num FROM alembic_version"))
    assert result.scalar_one() == EXPECTED_REVISION


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_users_table_has_is_admin_column(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'is_admin'
            """
        )
    )
    assert result.scalar_one() == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_ingestion_queue_table_has_status_and_drop_columns(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'ingestion_queue_items'
              AND column_name IN ('status', 'dropped_reason', 'dropped_at')
            """
        )
    )
    columns = {row[0] for row in result}
    assert columns == {"status", "dropped_reason", "dropped_at"}


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_crawl_runs_table_has_idempotency_key_column(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'crawl_runs' AND column_name = 'idempotency_key'
            """
        )
    )
    assert result.scalar_one() == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_crawl_runs_has_manual_idempotency_unique_index(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'crawl_runs'
              AND indexname = 'uq_crawl_runs_user_manual_idempotency_key'
            """
        )
    )
    indexdef = result.scalar_one()
    assert "UNIQUE INDEX" in indexdef
    assert "(user_id, idempotency_key)" in indexdef
    assert "WHERE" in indexdef


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_scholar_profiles_has_profile_image_columns(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'scholar_profiles'
              AND column_name IN (
                'profile_image_url',
                'profile_image_override_url',
                'profile_image_upload_path'
              )
            """
        )
    )
    columns = {row[0] for row in result}
    assert columns == {
        "profile_image_url",
        "profile_image_override_url",
        "profile_image_upload_path",
    }


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.migrations
@pytest.mark.asyncio
async def test_scholar_profiles_has_initial_page_snapshot_columns(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'scholar_profiles'
              AND column_name IN (
                'last_initial_page_fingerprint_sha256',
                'last_initial_page_checked_at'
              )
            """
        )
    )
    columns = {row[0] for row in result}
    assert columns == {
        "last_initial_page_fingerprint_sha256",
        "last_initial_page_checked_at",
    }
