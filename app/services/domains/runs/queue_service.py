from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionQueueItem
from app.services.domains.ingestion import queue as queue_mutations
from app.services.domains.runs.queue_queries import queue_item_select, queue_list_item_from_row
from app.services.domains.runs.types import (
    QUEUE_STATUS_DROPPED,
    QUEUE_STATUS_QUEUED,
    QUEUE_STATUS_RETRYING,
    QueueClearResult,
    QueueListItem,
    QueueTransitionError,
)


async def list_queue_items_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    limit: int = 200,
) -> list[QueueListItem]:
    result = await db_session.execute(
        queue_item_select(user_id=user_id)
        .order_by(
            case((IngestionQueueItem.status == QUEUE_STATUS_DROPPED, 1), else_=0).asc(),
            IngestionQueueItem.next_attempt_dt.asc(),
            IngestionQueueItem.id.asc(),
        )
        .limit(limit)
    )
    return [queue_list_item_from_row(row) for row in result.all()]


async def get_queue_item_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    queue_item_id: int,
) -> QueueListItem | None:
    result = await db_session.execute(
        queue_item_select(user_id=user_id)
        .where(IngestionQueueItem.id == queue_item_id)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return queue_list_item_from_row(row)


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

    await queue_mutations.mark_queued_now(
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

    await queue_mutations.mark_dropped(
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
    deleted = await queue_mutations.delete_job_by_id(db_session, job_id=item_id)
    await db_session.commit()
    if not deleted:
        return None
    return QueueClearResult(queue_item_id=item_id, previous_status=previous_status)


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
    counts: dict[str, int] = {
        QUEUE_STATUS_QUEUED: 0,
        QUEUE_STATUS_RETRYING: 0,
        QUEUE_STATUS_DROPPED: 0,
    }
    for status, count in result.all():
        counts[str(status)] = int(count or 0)
    return counts
