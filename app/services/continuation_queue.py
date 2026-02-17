from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionQueueItem, QueueItemStatus


@dataclass(frozen=True)
class ContinuationQueueJob:
    id: int
    user_id: int
    scholar_profile_id: int
    resume_cstart: int
    reason: str
    status: str
    attempt_count: int
    next_attempt_dt: datetime


ACTIVE_QUEUE_STATUSES: tuple[str, ...] = (
    QueueItemStatus.QUEUED.value,
    QueueItemStatus.RETRYING.value,
)


def normalize_cstart(value: int | None) -> int:
    if value is None:
        return 0
    return max(0, int(value))


def compute_backoff_seconds(*, base_seconds: int, attempt_count: int, max_seconds: int) -> int:
    base = max(1, int(base_seconds))
    attempts = max(1, int(attempt_count))
    maximum = max(base, int(max_seconds))
    seconds = base * (2 ** max(0, attempts - 1))
    return min(seconds, maximum)


async def upsert_job(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
    resume_cstart: int,
    reason: str,
    run_id: int | None,
    delay_seconds: int,
) -> IngestionQueueItem:
    now = datetime.now(timezone.utc)
    next_attempt_dt = now + timedelta(seconds=max(0, int(delay_seconds)))
    result = await db_session.execute(
        select(IngestionQueueItem).where(
            IngestionQueueItem.user_id == user_id,
            IngestionQueueItem.scholar_profile_id == scholar_profile_id,
        )
    )
    item = result.scalar_one_or_none()
    normalized_cstart = normalize_cstart(resume_cstart)
    if item is None:
        item = IngestionQueueItem(
            user_id=user_id,
            scholar_profile_id=scholar_profile_id,
            resume_cstart=normalized_cstart,
            reason=reason,
            status=QueueItemStatus.QUEUED.value,
            attempt_count=0,
            next_attempt_dt=next_attempt_dt,
            last_run_id=run_id,
            last_error=None,
            dropped_reason=None,
            dropped_at=None,
            created_at=now,
            updated_at=now,
        )
        db_session.add(item)
        return item

    item.resume_cstart = normalized_cstart
    item.reason = reason
    if item.status == QueueItemStatus.DROPPED.value:
        item.attempt_count = 0
    item.status = QueueItemStatus.QUEUED.value
    item.next_attempt_dt = next_attempt_dt
    item.last_run_id = run_id
    item.last_error = None
    item.dropped_reason = None
    item.dropped_at = None
    item.updated_at = now
    return item


async def clear_job_for_scholar(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
) -> bool:
    result = await db_session.execute(
        select(IngestionQueueItem).where(
            IngestionQueueItem.user_id == user_id,
            IngestionQueueItem.scholar_profile_id == scholar_profile_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return False
    await db_session.delete(item)
    return True


async def delete_job_by_id(
    db_session: AsyncSession,
    *,
    job_id: int,
) -> bool:
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return False
    await db_session.delete(item)
    return True


async def list_due_jobs(
    db_session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> list[ContinuationQueueJob]:
    result = await db_session.execute(
        select(IngestionQueueItem)
        .where(
            IngestionQueueItem.next_attempt_dt <= now,
            IngestionQueueItem.status.in_(ACTIVE_QUEUE_STATUSES),
        )
        .order_by(
            IngestionQueueItem.next_attempt_dt.asc(),
            IngestionQueueItem.id.asc(),
        )
        .limit(limit)
    )
    rows = list(result.scalars().all())
    jobs: list[ContinuationQueueJob] = []
    for row in rows:
        jobs.append(
            ContinuationQueueJob(
                id=int(row.id),
                user_id=int(row.user_id),
                scholar_profile_id=int(row.scholar_profile_id),
                resume_cstart=normalize_cstart(row.resume_cstart),
                reason=row.reason,
                status=row.status,
                attempt_count=int(row.attempt_count),
                next_attempt_dt=row.next_attempt_dt,
            )
        )
    return jobs


async def increment_attempt_count(
    db_session: AsyncSession,
    *,
    job_id: int,
) -> IngestionQueueItem | None:
    now = datetime.now(timezone.utc)
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.attempt_count = int(item.attempt_count or 0) + 1
    item.updated_at = now
    return item


async def reset_attempt_count(
    db_session: AsyncSession,
    *,
    job_id: int,
) -> IngestionQueueItem | None:
    now = datetime.now(timezone.utc)
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.attempt_count = 0
    item.updated_at = now
    return item


async def reschedule_job(
    db_session: AsyncSession,
    *,
    job_id: int,
    delay_seconds: int,
    reason: str,
    error: str | None = None,
) -> IngestionQueueItem | None:
    now = datetime.now(timezone.utc)
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.next_attempt_dt = now + timedelta(seconds=max(1, int(delay_seconds)))
    item.status = QueueItemStatus.QUEUED.value
    item.reason = reason
    item.last_error = error
    item.dropped_reason = None
    item.dropped_at = None
    item.updated_at = now
    return item


async def mark_retrying(
    db_session: AsyncSession,
    *,
    job_id: int,
    reason: str | None = None,
) -> IngestionQueueItem | None:
    now = datetime.now(timezone.utc)
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    if item.status == QueueItemStatus.DROPPED.value:
        return item
    item.status = QueueItemStatus.RETRYING.value
    if reason:
        item.reason = reason
    item.updated_at = now
    return item


async def mark_dropped(
    db_session: AsyncSession,
    *,
    job_id: int,
    reason: str,
    error: str | None = None,
) -> IngestionQueueItem | None:
    now = datetime.now(timezone.utc)
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.status = QueueItemStatus.DROPPED.value
    item.reason = "dropped"
    item.dropped_reason = reason
    item.dropped_at = now
    if error is not None:
        item.last_error = error
    item.updated_at = now
    return item


async def mark_queued_now(
    db_session: AsyncSession,
    *,
    job_id: int,
    reason: str,
    reset_attempt_count: bool = False,
) -> IngestionQueueItem | None:
    now = datetime.now(timezone.utc)
    result = await db_session.execute(
        select(IngestionQueueItem).where(IngestionQueueItem.id == job_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.status = QueueItemStatus.QUEUED.value
    item.reason = reason
    item.next_attempt_dt = now
    if reset_attempt_count:
        item.attempt_count = 0
    item.last_error = None
    item.dropped_reason = None
    item.dropped_at = None
    item.updated_at = now
    return item
