from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    IngestionQueueItem,
    RunStatus,
    RunTriggerType,
    ScholarProfile,
)
from app.services import continuation_queue as queue_service

QUEUE_STATUS_QUEUED = "queued"
QUEUE_STATUS_RETRYING = "retrying"
QUEUE_STATUS_DROPPED = "dropped"


@dataclass(frozen=True)
class QueueListItem:
    id: int
    scholar_profile_id: int
    scholar_label: str
    status: str
    reason: str
    dropped_reason: str | None
    attempt_count: int
    resume_cstart: int
    next_attempt_dt: datetime | None
    updated_at: datetime
    last_error: str | None
    last_run_id: int | None


@dataclass(frozen=True)
class QueueClearResult:
    queue_item_id: int
    previous_status: str


class QueueTransitionError(RuntimeError):
    def __init__(self, *, code: str, message: str, current_status: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.current_status = current_status


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _summary_dict(error_log: object) -> dict[str, Any]:
    if not isinstance(error_log, dict):
        return {}
    summary = error_log.get("summary")
    if not isinstance(summary, dict):
        return {}
    return summary


def _summary_int_dict(summary: dict[str, Any], key: str) -> dict[str, int]:
    value = summary.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): _safe_int(item_value, 0)
        for item_key, item_value in value.items()
        if isinstance(item_key, str)
    }


def _summary_bool_dict(summary: dict[str, Any], key: str) -> dict[str, bool]:
    value = summary.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): bool(item_value)
        for item_key, item_value in value.items()
        if isinstance(item_key, str)
    }


def extract_run_summary(error_log: object) -> dict[str, Any]:
    summary = _summary_dict(error_log)
    return {
        "succeeded_count": _safe_int(summary.get("succeeded_count", 0)),
        "failed_count": _safe_int(summary.get("failed_count", 0)),
        "partial_count": _safe_int(summary.get("partial_count", 0)),
        "failed_state_counts": _summary_int_dict(summary, "failed_state_counts"),
        "failed_reason_counts": _summary_int_dict(summary, "failed_reason_counts"),
        "scrape_failure_counts": _summary_int_dict(summary, "scrape_failure_counts"),
        "retry_counts": {
            "retries_scheduled_count": _safe_int(
                (
                    summary.get("retry_counts", {}).get("retries_scheduled_count")
                    if isinstance(summary.get("retry_counts"), dict)
                    else 0
                ),
                0,
            ),
            "scholars_with_retries_count": _safe_int(
                (
                    summary.get("retry_counts", {}).get("scholars_with_retries_count")
                    if isinstance(summary.get("retry_counts"), dict)
                    else 0
                ),
                0,
            ),
            "retry_exhausted_count": _safe_int(
                (
                    summary.get("retry_counts", {}).get("retry_exhausted_count")
                    if isinstance(summary.get("retry_counts"), dict)
                    else 0
                ),
                0,
            ),
        },
        "alert_thresholds": _summary_int_dict(summary, "alert_thresholds"),
        "alert_flags": _summary_bool_dict(summary, "alert_flags"),
    }


def _queue_item_columns() -> tuple:
    return (
        IngestionQueueItem.id,
        IngestionQueueItem.scholar_profile_id,
        ScholarProfile.display_name,
        ScholarProfile.scholar_id,
        IngestionQueueItem.status,
        IngestionQueueItem.reason,
        IngestionQueueItem.dropped_reason,
        IngestionQueueItem.attempt_count,
        IngestionQueueItem.resume_cstart,
        IngestionQueueItem.next_attempt_dt,
        IngestionQueueItem.updated_at,
        IngestionQueueItem.last_error,
        IngestionQueueItem.last_run_id,
    )


def _queue_item_select(*, user_id: int):
    return (
        select(*_queue_item_columns())
        .join(
            ScholarProfile,
            and_(
                ScholarProfile.id == IngestionQueueItem.scholar_profile_id,
                ScholarProfile.user_id == IngestionQueueItem.user_id,
            ),
        )
        .where(IngestionQueueItem.user_id == user_id)
    )


def _queue_list_item_from_row(row: tuple) -> QueueListItem:
    (
        item_id,
        scholar_profile_id,
        display_name,
        scholar_id,
        status,
        reason,
        dropped_reason,
        attempt_count,
        resume_cstart,
        next_attempt_dt,
        updated_at,
        last_error,
        last_run_id,
    ) = row
    return QueueListItem(
        id=int(item_id),
        scholar_profile_id=int(scholar_profile_id),
        scholar_label=(display_name or scholar_id),
        status=str(status),
        reason=str(reason),
        dropped_reason=dropped_reason,
        attempt_count=int(attempt_count or 0),
        resume_cstart=int(resume_cstart or 0),
        next_attempt_dt=next_attempt_dt,
        updated_at=updated_at,
        last_error=last_error,
        last_run_id=int(last_run_id) if last_run_id is not None else None,
    )


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


async def list_queue_items_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    limit: int = 200,
) -> list[QueueListItem]:
    result = await db_session.execute(
        _queue_item_select(user_id=user_id)
        .order_by(
            case((IngestionQueueItem.status == "dropped", 1), else_=0).asc(),
            IngestionQueueItem.next_attempt_dt.asc(),
            IngestionQueueItem.id.asc(),
        )
        .limit(limit)
    )
    return [_queue_list_item_from_row(row) for row in result.all()]


async def get_queue_item_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    queue_item_id: int,
) -> QueueListItem | None:
    result = await db_session.execute(
        _queue_item_select(user_id=user_id)
        .where(IngestionQueueItem.id == queue_item_id)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return _queue_list_item_from_row(row)


async def retry_queue_item_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    queue_item_id: int,
) -> QueueListItem | None:
    result = await db_session.execute(
        select(IngestionQueueItem).where(
            IngestionQueueItem.id == queue_item_id,
            IngestionQueueItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    if item.status == QUEUE_STATUS_QUEUED:
        raise QueueTransitionError(
            code="queue_item_already_queued",
            message="Queue item is already queued.",
            current_status=item.status,
        )
    if item.status == QUEUE_STATUS_RETRYING:
        raise QueueTransitionError(
            code="queue_item_retrying",
            message="Queue item is currently retrying.",
            current_status=item.status,
        )

    await queue_service.mark_queued_now(
        db_session,
        job_id=item.id,
        reason="manual_retry",
        reset_attempt_count=(item.status == QUEUE_STATUS_DROPPED),
    )
    await db_session.commit()

    return await get_queue_item_for_user(
        db_session,
        user_id=user_id,
        queue_item_id=queue_item_id,
    )


async def drop_queue_item_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    queue_item_id: int,
) -> QueueListItem | None:
    result = await db_session.execute(
        select(IngestionQueueItem).where(
            IngestionQueueItem.id == queue_item_id,
            IngestionQueueItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    if item.status == QUEUE_STATUS_DROPPED:
        raise QueueTransitionError(
            code="queue_item_already_dropped",
            message="Queue item is already dropped.",
            current_status=item.status,
        )

    await queue_service.mark_dropped(
        db_session,
        job_id=int(item.id),
        reason="manual_drop",
    )
    await db_session.commit()
    return await get_queue_item_for_user(
        db_session,
        user_id=user_id,
        queue_item_id=queue_item_id,
    )


async def clear_queue_item_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    queue_item_id: int,
) -> QueueClearResult | None:
    result = await db_session.execute(
        select(IngestionQueueItem).where(
            IngestionQueueItem.id == queue_item_id,
            IngestionQueueItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    if item.status != QUEUE_STATUS_DROPPED:
        raise QueueTransitionError(
            code="queue_item_not_dropped",
            message="Queue item can only be cleared after it is dropped.",
            current_status=item.status,
        )

    item_id = int(item.id)
    previous_status = str(item.status)
    deleted = await queue_service.delete_job_by_id(
        db_session,
        job_id=item_id,
    )
    await db_session.commit()
    if not deleted:
        return None
    return QueueClearResult(
        queue_item_id=item_id,
        previous_status=previous_status,
    )


async def queue_status_counts_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> dict[str, int]:
    result = await db_session.execute(
        select(
            IngestionQueueItem.status,
            func.count(IngestionQueueItem.id),
        )
        .where(IngestionQueueItem.user_id == user_id)
        .group_by(IngestionQueueItem.status)
    )
    counts: dict[str, int] = {"queued": 0, "retrying": 0, "dropped": 0}
    for status, count in result.all():
        counts[str(status)] = int(count or 0)
    return counts
