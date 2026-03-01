from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Publication,
    PublicationPdfJob,
    ScholarProfile,
    ScholarPublication,
    User,
)
from app.services.publication_identifiers import application as identifier_service
from app.services.publication_identifiers.types import DisplayIdentifier
from app.services.publications.pdf_queue_common import (
    PDF_STATUS_QUEUED,
    PDF_STATUS_RUNNING,
    PDF_STATUS_UNTRACKED,
)
from app.services.publications.types import PublicationListItem


def _bounded_limit(limit: int, *, max_value: int = 500) -> int:
    return max(1, min(int(limit), max_value))


def _bounded_offset(offset: int) -> int:
    return max(int(offset), 0)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _retry_item_label(display_name: str | None, scholar_id: str | None) -> str:
    return str(display_name or scholar_id or "unknown")


def _retry_item_from_publication(
    publication: Publication,
    *,
    link_row: Any | None,
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
        pdf_url=publication.pdf_url,
        is_read=is_read,
        first_seen_at=first_seen_at,
        is_new_in_latest_run=False,
    )


async def retry_item_for_publication_id(
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


def _queue_candidate_from_publication(publication: Publication) -> PublicationListItem:
    return PublicationListItem(
        publication_id=int(publication.id),
        scholar_profile_id=0,
        scholar_label="",
        title=publication.title_raw,
        year=publication.year,
        citation_count=int(publication.citation_count or 0),
        venue_text=publication.venue_text,
        pub_url=publication.pub_url,
        pdf_url=publication.pdf_url,
        is_read=True,
        first_seen_at=publication.created_at or _utcnow(),
        is_new_in_latest_run=False,
    )


async def missing_pdf_candidates(
    db_session: AsyncSession,
    *,
    limit: int,
) -> list[PublicationListItem]:
    bounded_limit = max(1, min(int(limit), 5000))
    now = datetime.now(UTC)
    cooldown_threshold = now - timedelta(days=7)

    result = await db_session.execute(
        select(Publication)
        .outerjoin(PublicationPdfJob, PublicationPdfJob.publication_id == Publication.id)
        .where(Publication.pdf_url.is_(None))
        .where(
            or_(
                PublicationPdfJob.publication_id.is_(None),
                and_(
                    PublicationPdfJob.status.notin_([PDF_STATUS_QUEUED, PDF_STATUS_RUNNING]),
                    or_(
                        PublicationPdfJob.last_attempt_at.is_(None),
                        PublicationPdfJob.last_attempt_at < cooldown_threshold,
                    ),
                ),
            )
        )
        .order_by(Publication.updated_at.desc(), Publication.id.desc())
        .limit(bounded_limit)
    )
    return [_queue_candidate_from_publication(publication) for publication in result.scalars()]


# ---------------------------------------------------------------------------
# Tracked / untracked queue SQL builders
# ---------------------------------------------------------------------------


def _tracked_queue_select_base(*, status: str | None) -> Select[tuple]:
    stmt = (
        select(
            PublicationPdfJob.publication_id,
            Publication.title_raw,
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


# ---------------------------------------------------------------------------
# Row hydration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdfQueueListItem:
    publication_id: int
    title: str
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
    display_identifier: DisplayIdentifier | None = None


def _queue_item_from_row(row: Any) -> PdfQueueListItem:
    return PdfQueueListItem(
        publication_id=int(row[0]),
        title=str(row[1] or ""),
        pdf_url=row[2],
        status=str(row[3] or PDF_STATUS_UNTRACKED),
        attempt_count=int(row[4] or 0),
        last_failure_reason=row[5],
        last_failure_detail=row[6],
        last_source=row[7],
        requested_by_user_id=int(row[8]) if row[8] is not None else None,
        requested_by_email=row[9],
        queued_at=row[10],
        last_attempt_at=row[11],
        resolved_at=row[12],
        updated_at=row[13],
    )


async def _hydrated_queue_items(
    db_session: AsyncSession,
    *,
    rows: list[Any],
) -> list[PdfQueueListItem]:
    items = [_queue_item_from_row(row) for row in rows]
    return await identifier_service.overlay_pdf_queue_items_with_display_identifiers(
        db_session,
        items=items,
    )


# ---------------------------------------------------------------------------
# Public listing / counting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdfQueuePage:
    items: list[PdfQueueListItem]
    total_count: int
    limit: int
    offset: int


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
        return await _hydrated_queue_items(db_session, rows=list(result.all()))
    if normalized_status is None:
        result = await db_session.execute(
            _all_queue_select(
                limit=bounded_limit,
                offset=bounded_offset,
            )
        )
        return await _hydrated_queue_items(db_session, rows=list(result.all()))
    result = await db_session.execute(
        _tracked_queue_select(
            limit=bounded_limit,
            offset=bounded_offset,
            status=normalized_status,
        )
    )
    return await _hydrated_queue_items(db_session, rows=list(result.all()))


async def count_pdf_queue_items(
    db_session: AsyncSession,
    *,
    status: str | None = None,
) -> int:
    normalized_status = (status or "").strip().lower() or None
    if normalized_status == PDF_STATUS_UNTRACKED:
        result = await db_session.execute(_untracked_queue_count_select())
        return int(result.scalar_one() or 0)
    tracked_result = await db_session.execute(_tracked_queue_count_select(status=normalized_status))
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
