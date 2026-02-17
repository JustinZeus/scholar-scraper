import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.db
@pytest.mark.asyncio
async def test_schema_head_revision_is_available(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT version_num FROM alembic_version"))
    assert result.scalar_one() == "20260217_0007"


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.db
@pytest.mark.asyncio
async def test_user_table_exists_in_public_schema(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT 1
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = 'users'
            """
        )
    )
    assert result.scalar_one() == 1


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.db
@pytest.mark.asyncio
async def test_users_table_includes_admin_column(db_session: AsyncSession) -> None:
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
