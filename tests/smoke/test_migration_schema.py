from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def expected_head_revision() -> str:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    head = script.get_current_head()
    assert head is not None
    return head


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.db
@pytest.mark.asyncio
async def test_schema_head_revision_is_available(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT version_num FROM alembic_version"))
    assert result.scalar_one() == expected_head_revision()


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
