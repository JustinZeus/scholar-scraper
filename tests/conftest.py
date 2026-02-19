from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.deps import get_login_rate_limiter
from app.db.session import close_engine
from app.settings import settings

RESET_SQL = text(
    """
    TRUNCATE TABLE
      author_search_cache_entries,
      author_search_runtime_state,
      ingestion_queue_items,
      scholar_publications,
      crawl_runs,
      scholar_profiles,
      publications,
      user_settings,
      users
    RESTART IDENTITY CASCADE
    """
)

DB_NAME_SAFE_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _resolve_test_database_url() -> str | None:
    explicit = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if explicit:
        return explicit

    base = (os.getenv("DATABASE_URL") or "").strip()
    if not base:
        return None

    parsed = make_url(base)
    if not parsed.database:
        return None
    derived_database = (
        parsed.database if parsed.database.endswith("_test") else f"{parsed.database}_test"
    )
    return parsed.set(database=derived_database).render_as_string(hide_password=False)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "integration" in item.keywords and not _resolve_test_database_url():
        pytest.skip("DATABASE_URL (or TEST_DATABASE_URL) is required for integration tests")


@pytest.fixture(scope="session")
def database_url() -> str:
    value = _resolve_test_database_url()
    if not value:
        pytest.skip("DATABASE_URL (or TEST_DATABASE_URL) is required for database tests")
    return value


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def ensure_test_database_exists(database_url: str) -> Iterator[None]:
    parsed = make_url(database_url)
    database_name = parsed.database
    if not database_name:
        raise RuntimeError("TEST_DATABASE_URL must include a database name.")
    if not DB_NAME_SAFE_RE.fullmatch(database_name):
        raise RuntimeError(
            "TEST_DATABASE_URL database name must match [A-Za-z0-9_]+ for safe auto-provisioning."
        )

    admin_name = "postgres" if database_name != "postgres" else "template1"
    admin_url = parsed.set(database=admin_name)
    admin_url_rendered = admin_url.render_as_string(hide_password=False)

    async def _ensure_database() -> None:
        engine = create_async_engine(
            admin_url_rendered,
            pool_pre_ping=True,
            isolation_level="AUTOCOMMIT",
        )
        try:
            async with engine.connect() as connection:
                exists_result = await connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                    {"database_name": database_name},
                )
                if exists_result.scalar_one_or_none() == 1:
                    return
                try:
                    await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
                except Exception as exc:
                    raise RuntimeError(
                        "Unable to auto-create test database. "
                        "Create it manually or grant CREATEDB to the database user."
                    ) from exc
        finally:
            await engine.dispose()

    asyncio.run(_ensure_database())
    yield


@pytest.fixture(scope="session")
def migrated_database(
    alembic_config: Config,
    ensure_test_database_exists: None,
    database_url: str,
) -> Iterator[None]:
    previous_env_database_url = os.getenv("DATABASE_URL")
    previous_settings_database_url = settings.database_url

    os.environ["DATABASE_URL"] = database_url
    object.__setattr__(settings, "database_url", database_url)
    asyncio.run(close_engine())
    command.upgrade(alembic_config, "head")

    try:
        yield
    finally:
        if previous_env_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_env_database_url
        object.__setattr__(settings, "database_url", previous_settings_database_url)
        asyncio.run(close_engine())


@pytest.fixture
async def db_session(
    migrated_database: None,
    database_url: str,
) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.execute(RESET_SQL)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_rate_limiter_state() -> Iterator[None]:
    limiter = get_login_rate_limiter()
    limiter.clear_all()
    yield
    limiter.clear_all()


@pytest.fixture(autouse=True)
async def reset_app_engine() -> AsyncIterator[None]:
    await close_engine()
    yield
    await close_engine()
