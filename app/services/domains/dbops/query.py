from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataRepairJob


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), 200))


async def list_repair_jobs(
    db_session: AsyncSession,
    *,
    limit: int = 50,
) -> list[DataRepairJob]:
    bounded = _bounded_limit(limit)
    result = await db_session.execute(
        select(DataRepairJob).order_by(DataRepairJob.created_at.desc()).limit(bounded)
    )
    return list(result.scalars())
