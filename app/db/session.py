from collections.abc import AsyncIterator
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.settings import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # NullPool avoids cross-event-loop connection reuse in tests and dev tools.
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
        logger.info("db.engine_initialized", extra={"event": "db.engine_initialized"})
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def check_database() -> bool:
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar_one() == 1
    except Exception:
        logger.exception("db.healthcheck_failed", extra={"event": "db.healthcheck_failed"})
        return False


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("db.engine_disposed", extra={"event": "db.engine_disposed"})
        _engine = None
        _session_factory = None
