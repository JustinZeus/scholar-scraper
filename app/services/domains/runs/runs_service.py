from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlRun, RunStatus, RunTriggerType


async def list_recent_runs_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    limit: int = 20,
) -> list[CrawlRun]:
    result = await db_session.execute(
        select(CrawlRun)
        .where(CrawlRun.user_id == user_id)
        .order_by(CrawlRun.start_dt.desc(), CrawlRun.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_runs_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
    failed_only: bool = False,
) -> list[CrawlRun]:
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.user_id == user_id)
        .order_by(CrawlRun.start_dt.desc(), CrawlRun.id.desc())
        .limit(limit)
    )
    if failed_only:
        stmt = stmt.where(
            CrawlRun.status.in_([RunStatus.FAILED, RunStatus.PARTIAL_FAILURE])
        )
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


async def get_run_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    run_id: int,
) -> CrawlRun | None:
    result = await db_session.execute(
        select(CrawlRun).where(
            CrawlRun.user_id == user_id,
            CrawlRun.id == run_id,
        )
    )
    return result.scalar_one_or_none()


async def get_manual_run_by_idempotency_key(
    db_session: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
) -> CrawlRun | None:
    result = await db_session.execute(
        select(CrawlRun)
        .where(
            CrawlRun.user_id == user_id,
            CrawlRun.trigger_type == RunTriggerType.MANUAL,
            or_(
                CrawlRun.idempotency_key == idempotency_key,
                CrawlRun.error_log["meta"]["idempotency_key"].astext == idempotency_key,
            ),
        )
        .order_by(CrawlRun.start_dt.desc(), CrawlRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
