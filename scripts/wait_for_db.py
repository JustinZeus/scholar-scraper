import asyncio
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.logging_config import configure_logging, parse_redact_fields
from app.settings import settings

configure_logging(
    level=settings.log_level,
    log_format=settings.log_format,
    redact_fields=parse_redact_fields(settings.log_redact_fields),
    include_uvicorn_access=settings.log_uvicorn_access,
)

logger = logging.getLogger(__name__)


async def can_connect(database_url: str) -> bool:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar_one() == 1
    except Exception:
        return False
    finally:
        await engine.dispose()


async def wait_for_database() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("db.wait_missing_database_url", extra={"event": "db.wait_missing_database_url"})
        return 1

    timeout_seconds = int(os.getenv("DB_WAIT_TIMEOUT_SECONDS", "60"))
    interval_seconds = int(os.getenv("DB_WAIT_INTERVAL_SECONDS", "2"))
    retries = max(timeout_seconds // max(interval_seconds, 1), 1)

    for attempt in range(1, retries + 1):
        if await can_connect(database_url):
            logger.info("db.wait_ready", extra={"event": "db.wait_ready"})
            return 0
        logger.info(
            "db.wait_retry",
            extra={
                "event": "db.wait_retry",
                "attempt": attempt,
                "retries": retries,
            },
        )
        await asyncio.sleep(interval_seconds)

    logger.error(
        "db.wait_timeout",
        extra={
            "event": "db.wait_timeout",
            "retries": retries,
        },
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(wait_for_database()))
