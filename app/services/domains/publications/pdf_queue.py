from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import Select, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Publication,
    PublicationPdfJob,
    PublicationPdfJobEvent,
    ScholarProfile,
    ScholarPublication,
    User,
)
from app.db.session import get_session_factory
from app.services.domains.publications.types import PublicationListItem
from app.services.domains.unpaywall.application import (
    FAILURE_RESOLUTION_EXCEPTION,
    OaResolutionOutcome,
    resolve_publication_oa_outcomes,
)
from app.settings import settings

PDF_STATUS_UNTRACKED = "untracked"
PDF_STATUS_QUEUED = "queued"
PDF_STATUS_RUNNING = "running"
PDF_STATUS_RESOLVED = "resolved"
PDF_STATUS_FAILED = "failed"

PDF_EVENT_QUEUED = "queued"
PDF_EVENT_ATTEMPT_STARTED = "attempt_started"
PDF_EVENT_RESOLVED = "resolved"
PDF_EVENT_FAILED = "failed"

logger = logging.getLogger(__name__)
_scheduled_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class PdfQueueListItem:
    publication_id: int
    title: str
    doi: str | None
    pdf_url: str | None
    status: str
    attempt_count: int
    last_failure_reason: str | None
    last_failure_detail: str | None
    last_source: str | None
    requested_by_user_id: int | None
    requested_by_email: str | None
    queued_at: datetime | None
    last_attempt_at: datetime | None
    resolved_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class PdfRequeueResult:
    publication_exists: bool
    queued: bool


@dataclass(frozen=True)
class PdfBulkQueueResult:
    requested_count: int
    queued_count: int


@dataclass(frozen=True)
class PdfQueuePage:
    items: list[PdfQueueListItem]
    total_count: int
    limit: int
    offset: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _publication_ids(rows: list[PublicationListItem]) -> list[int]:
    return sorted({row.publication_id for row in rows})


def _status_from_job(row: PublicationListItem, job: PublicationPdfJob | None) -> str:
    if row.pdf_url:
        return PDF_STATUS_RESOLVED
    if job is None:
        return PDF_STATUS_UNTRACKED
    return job.status


def _item_from_row_and_job(
    row: PublicationListItem,
    job: PublicationPdfJob | None,
) -> PublicationListItem:
    return PublicationListItem(
        publication_id=row.publication_id,
        scholar_profile_id=row.scholar_profile_id,
        scholar_label=row.scholar_label,
        title=row.title,
        year=row.year,
        citation_count=row.citation_count,
        venue_text=row.venue_text,
        pub_url=row.pub_url,
        doi=row.doi,
        pdf_url=row.pdf_url,
        is_read=row.is_read,
        is_favorite=row.is_favorite,
        first_seen_at=row.first_seen_at,
        is_new_in_latest_run=row.is_new_in_latest_run,
        pdf_status=_status_from_job(row, job),
        pdf_attempt_count=int(job.attempt_count) if job is not None else 0,
        pdf_failure_reason=job.last_failure_reason if job is not None else None,
        pdf_failure_detail=job.last_failure_detail if job is not None else None,
    )


def _queueable_rows(
    rows: list[PublicationListItem],
    *,
    max_items: int,
) -> list[PublicationListItem]:
    bounded = max(0, int(max_items))
    if bounded == 0:
        return []
    candidates = [row for row in rows if not row.pdf_url]
    return candidates[:bounded]


def _bounded_limit(limit: int, *, max_value: int = 500) -> int:
    return max(1, min(int(limit), max_value))


def _bounded_offset(offset: int) -> int:
    return max(int(offset), 0)


def _auto_retry_interval_seconds() -> int:
    return max(int(settings.pdf_auto_retry_interval_seconds), 1)


def _auto_retry_first_interval_seconds() -> int:
    return max(int(settings.pdf_auto_retry_first_interval_seconds), 1)


def _auto_retry_max_attempts() -> int:
    return max(int(settings.pdf_auto_retry_max_attempts), 1)


def _retry_interval_seconds_for_attempt_count(attempt_count: int) -> int:
    if int(attempt_count) <= 1:
        return _auto_retry_first_interval_seconds()
    return _auto_retry_interval_seconds()


def _cooldown_active(
    *,
    last_attempt_at: datetime | None,
    attempt_count: int,
) -> bool:
    if last_attempt_at is None:
        return False
    elapsed = (_utcnow() - last_attempt_at).total_seconds()
    return elapsed < _retry_interval_seconds_for_attempt_count(int(attempt_count))


def _can_enqueue_job(
    job: PublicationPdfJob | None,
    *,
    force_retry: bool,
) -> bool:
    if job is None:
        return True
    if job.status in {PDF_STATUS_QUEUED, PDF_STATUS_RUNNING}:
        return False
    if force_retry:
        return job.status in {PDF_STATUS_FAILED, PDF_STATUS_RESOLVED, PDF_STATUS_UNTRACKED}
    if job.status == PDF_STATUS_RESOLVED:
        return False
    if int(job.attempt_count) >= _auto_retry_max_attempts():
        return False
    if _cooldown_active(
        last_attempt_at=job.last_attempt_at,
        attempt_count=int(job.attempt_count),
    ):
        return False
    return True


def _event_row(
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


def _queued_job(
    *,
    publication_id: int,
    user_id: int,
) -> PublicationPdfJob:
    now = _utcnow()
    return PublicationPdfJob(
        publication_id=publication_id,
        status=PDF_STATUS_QUEUED,
        queued_at=now,
        last_requested_by_user_id=user_id,
    )


def _mark_job_queued(job: PublicationPdfJob, *, user_id: int) -> None:
    now = _utcnow()
    job.status = PDF_STATUS_QUEUED
    job.queued_at = now
    job.last_requested_by_user_id = user_id
    job.last_failure_reason = None
    job.last_failure_detail = None
    job.last_source = None


def _state_map(jobs: list[PublicationPdfJob]) -> dict[int, PublicationPdfJob]:
    return {int(job.publication_id): job for job in jobs}


async def _jobs_for_publication_ids(
    db_session: AsyncSession,
    *,
    publication_ids: list[int],
) -> dict[int, PublicationPdfJob]:
    if not publication_ids:
        return {}
    result = await db_session.execute(
        select(PublicationPdfJob).where(PublicationPdfJob.publication_id.in_(publication_ids))
    )
    return _state_map(list(result.scalars()))


async def overlay_pdf_job_state(
    db_session: AsyncSession,
    *,
    rows: list[PublicationListItem],
) -> list[PublicationListItem]:
    if not rows:
        return []
    jobs = await _jobs_for_publication_ids(
        db_session,
        publication_ids=_publication_ids(rows),
    )
    return [_item_from_row_and_job(row, jobs.get(row.publication_id)) for row in rows]


async def _enqueue_rows(
    db_session: AsyncSession,
    *,
    user_id: int,
    rows: list[PublicationListItem],
    force_retry: bool,
) -> list[PublicationListItem]:
    if not rows:
        return []
    queued: list[PublicationListItem] = []
    jobs = await _jobs_for_publication_ids(
        db_session,
        publication_ids=_publication_ids(rows),
    )
    for row in rows:
        job = jobs.get(row.publication_id)
        if not _can_enqueue_job(job, force_retry=force_retry):
            continue
        if job is None:
            job = _queued_job(publication_id=row.publication_id, user_id=user_id)
            jobs[row.publication_id] = job
            db_session.add(job)
        else:
            _mark_job_queued(job, user_id=user_id)
        db_session.add(
            _event_row(
                publication_id=row.publication_id,
                user_id=user_id,
                event_type=PDF_EVENT_QUEUED,
                status=PDF_STATUS_QUEUED,
            )
        )
        queued.append(row)
    if queued:
        await db_session.commit()
    return queued


def _register_task(task: asyncio.Task[None]) -> None:
    _scheduled_tasks.add(task)


def _drop_finished_task(task: asyncio.Task[None]) -> None:
    _scheduled_tasks.discard(task)
    try:
        task.result()
    except Exception:
        logger.exception(
            "publications.pdf_queue.task_failed",
            extra={"event": "publications.pdf_queue.task_failed"},
        )


async def _mark_attempt_started(
    *,
    publication_id: int,
    user_id: int,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        job = await db_session.get(PublicationPdfJob, publication_id)
        if job is None:
            job = _queued_job(publication_id=publication_id, user_id=user_id)
            db_session.add(job)
        job.status = PDF_STATUS_RUNNING
        job.last_attempt_at = _utcnow()
        job.attempt_count = int(job.attempt_count) + 1
        db_session.add(
            _event_row(
                publication_id=publication_id,
                user_id=user_id,
                event_type=PDF_EVENT_ATTEMPT_STARTED,
                status=PDF_STATUS_RUNNING,
            )
        )
        await db_session.commit()


def _failed_outcome(
    *,
    row: PublicationListItem,
) -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=row.publication_id,
        doi=row.doi,
        pdf_url=None,
        failure_reason=FAILURE_RESOLUTION_EXCEPTION,
        source=None,
        used_crossref=False,
    )


async def _fetch_outcome_for_row(
    *,
    row: PublicationListItem,
    request_email: str | None,
) -> OaResolutionOutcome:
    outcomes = await resolve_publication_oa_outcomes([row], request_email=request_email)
    outcome = outcomes.get(row.publication_id)
    if outcome is not None:
        return outcome
    return _failed_outcome(row=row)


def _apply_publication_update(
    publication: Publication,
    *,
    doi: str | None,
    pdf_url: str | None,
) -> None:
    if doi and publication.doi != doi:
        publication.doi = doi
    if pdf_url and publication.pdf_url != pdf_url:
        publication.pdf_url = pdf_url


def _apply_job_outcome(job: PublicationPdfJob, *, outcome: OaResolutionOutcome) -> None:
    job.last_source = outcome.source
    if outcome.pdf_url:
        job.status = PDF_STATUS_RESOLVED
        job.resolved_at = _utcnow()
        job.last_failure_reason = None
        job.last_failure_detail = None
        return
    job.status = PDF_STATUS_FAILED
    job.last_failure_reason = outcome.failure_reason
    job.last_failure_detail = outcome.failure_reason


def _result_event(outcome: OaResolutionOutcome) -> tuple[str, str]:
    if outcome.pdf_url:
        return PDF_EVENT_RESOLVED, PDF_STATUS_RESOLVED
    return PDF_EVENT_FAILED, PDF_STATUS_FAILED


async def _persist_outcome(
    *,
    publication_id: int,
    user_id: int,
    outcome: OaResolutionOutcome,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        publication = await db_session.get(Publication, publication_id)
        job = await db_session.get(PublicationPdfJob, publication_id)
        if publication is None or job is None:
            return
        _apply_publication_update(publication, doi=outcome.doi, pdf_url=outcome.pdf_url)
        _apply_job_outcome(job, outcome=outcome)
        event_type, status = _result_event(outcome)
        db_session.add(
            _event_row(
                publication_id=publication_id,
                user_id=user_id,
                event_type=event_type,
                status=status,
                source=outcome.source,
                failure_reason=outcome.failure_reason,
                message=outcome.failure_reason,
            )
        )
        await db_session.commit()


async def _resolve_publication_row(
    *,
    user_id: int,
    request_email: str | None,
    row: PublicationListItem,
) -> None:
    await _mark_attempt_started(publication_id=row.publication_id, user_id=user_id)
    try:
        outcome = await _fetch_outcome_for_row(row=row, request_email=request_email)
    except Exception as exc:  # pragma: no cover - defensive network boundary
        logger.warning(
            "publications.pdf_queue.resolve_failed",
            extra={
                "event": "publications.pdf_queue.resolve_failed",
                "publication_id": row.publication_id,
                "error": str(exc),
            },
        )
        outcome = _failed_outcome(row=row)
    await _persist_outcome(
        publication_id=row.publication_id,
        user_id=user_id,
        outcome=outcome,
    )


async def _run_resolution_task(
    *,
    user_id: int,
    request_email: str | None,
    rows: list[PublicationListItem],
) -> None:
    for row in rows:
        await _resolve_publication_row(
            user_id=user_id,
            request_email=request_email,
            row=row,
        )


def _schedule_rows(
    *,
    user_id: int,
    request_email: str | None,
    rows: list[PublicationListItem],
) -> None:
    if not rows:
        return
    task = asyncio.create_task(
        _run_resolution_task(
            user_id=user_id,
            request_email=request_email,
            rows=rows,
        )
    )
    _register_task(task)
    task.add_done_callback(_drop_finished_task)


async def enqueue_missing_pdf_jobs(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    rows: list[PublicationListItem],
    max_items: int,
) -> list[int]:
    queueable = _queueable_rows(rows, max_items=max_items)
    queued_rows = await _enqueue_rows(
        db_session,
        user_id=user_id,
        rows=queueable,
        force_retry=False,
    )
    _schedule_rows(user_id=user_id, request_email=request_email, rows=queued_rows)
    return [row.publication_id for row in queued_rows]


async def enqueue_retry_pdf_job(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    row: PublicationListItem,
) -> bool:
    queued_rows = await _enqueue_rows(
        db_session,
        user_id=user_id,
        rows=[row],
        force_retry=True,
    )
    _schedule_rows(user_id=user_id, request_email=request_email, rows=queued_rows)
    return bool(queued_rows)


def _retry_item_label(display_name: str | None, scholar_id: str | None) -> str:
    return str(display_name or scholar_id or "unknown")


def _retry_item_from_publication(
    publication: Publication,
    *,
    link_row: tuple | None,
) -> PublicationListItem:
    if link_row is None:
        scholar_profile_id = 0
        scholar_label = "unknown"
        is_read = True
        first_seen_at = publication.created_at or _utcnow()
    else:
        scholar_profile_id = int(link_row[0])
        scholar_label = _retry_item_label(link_row[1], link_row[2])
        is_read = bool(link_row[3])
        first_seen_at = link_row[4] or publication.created_at or _utcnow()
    return PublicationListItem(
        publication_id=int(publication.id),
        scholar_profile_id=scholar_profile_id,
        scholar_label=scholar_label,
        title=publication.title_raw,
        year=publication.year,
        citation_count=int(publication.citation_count or 0),
        venue_text=publication.venue_text,
        pub_url=publication.pub_url,
        doi=publication.doi,
        pdf_url=publication.pdf_url,
        is_read=is_read,
        first_seen_at=first_seen_at,
        is_new_in_latest_run=False,
    )


async def _retry_item_for_publication_id(
    db_session: AsyncSession,
    *,
    publication_id: int,
) -> PublicationListItem | None:
    publication = await db_session.get(Publication, publication_id)
    if publication is None:
        return None
    result = await db_session.execute(
        select(
            ScholarProfile.id,
            ScholarProfile.display_name,
            ScholarProfile.scholar_id,
            ScholarPublication.is_read,
            ScholarPublication.created_at,
        )
        .join(ScholarProfile, ScholarProfile.id == ScholarPublication.scholar_profile_id)
        .where(ScholarPublication.publication_id == publication_id)
        .order_by(ScholarPublication.created_at.asc())
        .limit(1)
    )
    return _retry_item_from_publication(publication, link_row=result.one_or_none())


async def enqueue_retry_pdf_job_for_publication_id(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    publication_id: int,
) -> PdfRequeueResult:
    row = await _retry_item_for_publication_id(
        db_session,
        publication_id=publication_id,
    )
    if row is None:
        return PdfRequeueResult(publication_exists=False, queued=False)
    queued = await enqueue_retry_pdf_job(
        db_session,
        user_id=user_id,
        request_email=request_email,
        row=row,
    )
    return PdfRequeueResult(publication_exists=True, queued=queued)


def _queue_candidate_from_publication(publication: Publication) -> PublicationListItem:
    return PublicationListItem(
        publication_id=int(publication.id),
        scholar_profile_id=0,
        scholar_label="admin",
        title=publication.title_raw,
        year=publication.year,
        citation_count=int(publication.citation_count or 0),
        venue_text=publication.venue_text,
        pub_url=publication.pub_url,
        doi=publication.doi,
        pdf_url=publication.pdf_url,
        is_read=True,
        first_seen_at=publication.created_at or _utcnow(),
        is_new_in_latest_run=False,
    )


async def _missing_pdf_candidates(
    db_session: AsyncSession,
    *,
    limit: int,
) -> list[PublicationListItem]:
    bounded_limit = max(1, min(int(limit), 5000))
    result = await db_session.execute(
        select(Publication)
        .outerjoin(PublicationPdfJob, PublicationPdfJob.publication_id == Publication.id)
        .where(Publication.pdf_url.is_(None))
        .where(
            or_(
                PublicationPdfJob.publication_id.is_(None),
                PublicationPdfJob.status.notin_([PDF_STATUS_QUEUED, PDF_STATUS_RUNNING]),
            )
        )
        .order_by(Publication.updated_at.desc(), Publication.id.desc())
        .limit(bounded_limit)
    )
    return [
        _queue_candidate_from_publication(publication)
        for publication in result.scalars()
    ]


async def enqueue_all_missing_pdf_jobs(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    limit: int = 1000,
) -> PdfBulkQueueResult:
    candidates = await _missing_pdf_candidates(db_session, limit=limit)
    queued_rows = await _enqueue_rows(
        db_session,
        user_id=user_id,
        rows=candidates,
        force_retry=True,
    )
    _schedule_rows(user_id=user_id, request_email=request_email, rows=queued_rows)
    return PdfBulkQueueResult(
        requested_count=len(candidates),
        queued_count=len(queued_rows),
    )


def _tracked_queue_select_base(*, status: str | None) -> Select[tuple]:
    stmt = (
        select(
            PublicationPdfJob.publication_id,
            Publication.title_raw,
            Publication.doi,
            Publication.pdf_url,
            PublicationPdfJob.status,
            PublicationPdfJob.attempt_count,
            PublicationPdfJob.last_failure_reason,
            PublicationPdfJob.last_failure_detail,
            PublicationPdfJob.last_source,
            PublicationPdfJob.last_requested_by_user_id,
            User.email,
            PublicationPdfJob.queued_at,
            PublicationPdfJob.last_attempt_at,
            PublicationPdfJob.resolved_at,
            PublicationPdfJob.updated_at,
        )
        .join(Publication, Publication.id == PublicationPdfJob.publication_id)
        .outerjoin(User, User.id == PublicationPdfJob.last_requested_by_user_id)
    )
    if status:
        stmt = stmt.where(PublicationPdfJob.status == status)
    return stmt


def _tracked_queue_select(*, limit: int, offset: int, status: str | None) -> Select[tuple]:
    return (
        _tracked_queue_select_base(status=status)
        .order_by(PublicationPdfJob.updated_at.desc())
        .limit(_bounded_limit(limit))
        .offset(_bounded_offset(offset))
    )


def _untracked_queue_select_base() -> Select[tuple]:
    return (
        select(
            Publication.id,
            Publication.title_raw,
            Publication.doi,
            Publication.pdf_url,
            literal(PDF_STATUS_UNTRACKED),
            literal(0),
            literal(None),
            literal(None),
            literal(None),
            literal(None),
            literal(None),
            literal(None),
            literal(None),
            literal(None),
            Publication.updated_at,
        )
        .outerjoin(PublicationPdfJob, PublicationPdfJob.publication_id == Publication.id)
        .where(Publication.pdf_url.is_(None))
        .where(PublicationPdfJob.publication_id.is_(None))
    )


def _untracked_queue_select(*, limit: int, offset: int) -> Select[tuple]:
    return (
        _untracked_queue_select_base()
        .order_by(Publication.updated_at.desc(), Publication.id.desc())
        .limit(_bounded_limit(limit))
        .offset(_bounded_offset(offset))
    )


def _all_queue_select(*, limit: int, offset: int) -> Select[tuple]:
    union_stmt = union_all(
        _tracked_queue_select_base(status=None),
        _untracked_queue_select_base(),
    ).subquery()
    return (
        select(union_stmt)
        .order_by(union_stmt.c.updated_at.desc())
        .limit(_bounded_limit(limit))
        .offset(_bounded_offset(offset))
    )


def _tracked_queue_count_select(*, status: str | None) -> Select[tuple]:
    stmt = select(func.count()).select_from(PublicationPdfJob)
    if status:
        stmt = stmt.where(PublicationPdfJob.status == status)
    return stmt


def _untracked_queue_count_select() -> Select[tuple]:
    return (
        select(func.count())
        .select_from(Publication)
        .outerjoin(PublicationPdfJob, PublicationPdfJob.publication_id == Publication.id)
        .where(Publication.pdf_url.is_(None))
        .where(PublicationPdfJob.publication_id.is_(None))
    )


def _queue_item_from_row(row: tuple) -> PdfQueueListItem:
    return PdfQueueListItem(
        publication_id=int(row[0]),
        title=str(row[1] or ""),
        doi=row[2],
        pdf_url=row[3],
        status=str(row[4] or PDF_STATUS_UNTRACKED),
        attempt_count=int(row[5] or 0),
        last_failure_reason=row[6],
        last_failure_detail=row[7],
        last_source=row[8],
        requested_by_user_id=int(row[9]) if row[9] is not None else None,
        requested_by_email=row[10],
        queued_at=row[11],
        last_attempt_at=row[12],
        resolved_at=row[13],
        updated_at=row[14],
    )


async def list_pdf_queue_items(
    db_session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
) -> list[PdfQueueListItem]:
    bounded_limit = _bounded_limit(limit)
    bounded_offset = _bounded_offset(offset)
    normalized_status = (status or "").strip().lower() or None
    if normalized_status == PDF_STATUS_UNTRACKED:
        result = await db_session.execute(
            _untracked_queue_select(
                limit=bounded_limit,
                offset=bounded_offset,
            )
        )
        return [_queue_item_from_row(row) for row in result.all()]
    if normalized_status is None:
        result = await db_session.execute(
            _all_queue_select(
                limit=bounded_limit,
                offset=bounded_offset,
            )
        )
        return [_queue_item_from_row(row) for row in result.all()]
    result = await db_session.execute(
        _tracked_queue_select(
            limit=bounded_limit,
            offset=bounded_offset,
            status=normalized_status,
        )
    )
    return [_queue_item_from_row(row) for row in result.all()]


async def count_pdf_queue_items(
    db_session: AsyncSession,
    *,
    status: str | None = None,
) -> int:
    normalized_status = (status or "").strip().lower() or None
    if normalized_status == PDF_STATUS_UNTRACKED:
        result = await db_session.execute(_untracked_queue_count_select())
        return int(result.scalar_one() or 0)
    tracked_result = await db_session.execute(
        _tracked_queue_count_select(status=normalized_status)
    )
    tracked_count = int(tracked_result.scalar_one() or 0)
    if normalized_status is not None:
        return tracked_count
    untracked_result = await db_session.execute(_untracked_queue_count_select())
    untracked_count = int(untracked_result.scalar_one() or 0)
    return tracked_count + untracked_count


async def list_pdf_queue_page(
    db_session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
) -> PdfQueuePage:
    bounded_limit = _bounded_limit(limit)
    bounded_offset = _bounded_offset(offset)
    items = await list_pdf_queue_items(
        db_session,
        limit=bounded_limit,
        offset=bounded_offset,
        status=status,
    )
    total_count = await count_pdf_queue_items(
        db_session,
        status=status,
    )
    return PdfQueuePage(
        items=items,
        total_count=total_count,
        limit=bounded_limit,
        offset=bounded_offset,
    )
