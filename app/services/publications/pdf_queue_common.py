from __future__ import annotations

from datetime import UTC, datetime

from app.db.models import PublicationPdfJob, PublicationPdfJobEvent

PDF_STATUS_UNTRACKED = "untracked"
PDF_STATUS_QUEUED = "queued"
PDF_STATUS_RUNNING = "running"
PDF_STATUS_RESOLVED = "resolved"
PDF_STATUS_FAILED = "failed"


def utcnow() -> datetime:
    return datetime.now(UTC)


def event_row(
    *,
    publication_id: int,
    user_id: int | None,
    event_type: str,
    status: str | None,
    source: str | None = None,
    failure_reason: str | None = None,
    message: str | None = None,
) -> PublicationPdfJobEvent:
    return PublicationPdfJobEvent(
        publication_id=publication_id,
        user_id=user_id,
        event_type=event_type,
        status=status,
        source=source,
        failure_reason=failure_reason,
        message=message,
    )


def queued_job(
    *,
    publication_id: int,
    user_id: int,
) -> PublicationPdfJob:
    now = utcnow()
    return PublicationPdfJob(
        publication_id=publication_id,
        status=PDF_STATUS_QUEUED,
        queued_at=now,
        last_requested_by_user_id=user_id,
    )
