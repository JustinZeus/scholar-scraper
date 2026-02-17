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
EXPECTED_REVISION = "20260217_0004"


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
