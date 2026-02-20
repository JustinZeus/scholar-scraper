from __future__ import annotations

from sqlalchemy import and_, select

from app.db.models import IngestionQueueItem, ScholarProfile
from app.services.domains.runs.types import QueueListItem


def queue_item_columns() -> tuple:
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


def queue_item_select(*, user_id: int):
    return (
        select(*queue_item_columns())
        .join(
            ScholarProfile,
            and_(
                ScholarProfile.id == IngestionQueueItem.scholar_profile_id,
                ScholarProfile.user_id == IngestionQueueItem.user_id,
            ),
        )
        .where(IngestionQueueItem.user_id == user_id)
    )


def queue_list_item_from_row(row: tuple) -> QueueListItem:
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
