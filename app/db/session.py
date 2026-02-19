from collections.abc import AsyncIterator
import logging
import os

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


def _normalized_pool_mode(raw_mode: str) -> str:
    mode = (raw_mode or "").strip().lower()
    if mode == "auto":
        if os.getenv("PYTEST_CURRENT_TEST"):
            return "null"
        app_env = (os.getenv("APP_ENV") or "").strip().lower()
        if app_env in {"test", "development", "dev", "local"}:
            return "null"
        return "queue"
    if mode in {"null", "queue"}:
        return mode
    logger.warning(
        "db.invalid_pool_mode_fallback",
        extra={
            "event": "db.invalid_pool_mode_fallback",
            "database_pool_mode": raw_mode,
            "fallback_mode": "queue",
        },
    )
    return "queue"


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        pool_mode = _normalized_pool_mode(settings.database_pool_mode)
        engine_kwargs: dict[str, object] = {
            "pool_pre_ping": True,
        }
        if pool_mode == "null":
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = max(1, int(settings.database_pool_size))
            engine_kwargs["max_overflow"] = max(0, int(settings.database_pool_max_overflow))
            engine_kwargs["pool_timeout"] = max(1, int(settings.database_pool_timeout_seconds))

        _engine = create_async_engine(settings.database_url, **engine_kwargs)
        logger.info(
            "db.engine_initialized",
            extra={
                "event": "db.engine_initialized",
                "pool_mode": pool_mode,
            },
        )
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
