import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_database_connectivity_from_database_url() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is not set")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()

