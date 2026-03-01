from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy import false as sa_false
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    Publication,
    PublicationPdfJob,
    RunStatus,
    ScholarProfile,
    ScholarPublication,
)
from app.services.publications.modes import MODE_LATEST, MODE_UNREAD
from app.services.publications.pdf_queue_common import (
    PDF_STATUS_FAILED,
    PDF_STATUS_QUEUED,
    PDF_STATUS_RESOLVED,
    PDF_STATUS_RUNNING,
)
from app.services.publications.types import PublicationListItem, UnreadPublicationItem


def _normalized_citation_count(value: object) -> int:
    try:
        return int(value or 0)  # type: ignore[call-overload]  # intentionally accepts any object
    except (TypeError, ValueError):
        return 0


def _pdf_status_sort_rank():
    return case(
        (Publication.pdf_url.is_not(None), 4),
        (PublicationPdfJob.status == PDF_STATUS_RESOLVED, 4),
        (PublicationPdfJob.status == PDF_STATUS_RUNNING, 3),
        (PublicationPdfJob.status == PDF_STATUS_QUEUED, 2),
        (PublicationPdfJob.status == PDF_STATUS_FAILED, 0),
        else_=1,
    )


def _sort_column(sort_by: str):
    sort_columns = {
        "first_seen": ScholarPublication.created_at,
        "title": Publication.title_raw,
        "year": Publication.year,
        "citations": Publication.citation_count,
        "scholar": ScholarProfile.display_name,
        "pdf_status": _pdf_status_sort_rank(),
    }
    return sort_columns.get(sort_by, ScholarPublication.created_at)


async def get_latest_run_id_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> int | None:
    # We include RUNNING and RESOLVING statuses so that the "New" tab shows
    # results in real-time as they are discovered.
    result = await db_session.execute(
        select(func.max(CrawlRun.id)).where(
            CrawlRun.user_id == user_id,
            CrawlRun.status.in_(
                [
                    RunStatus.RUNNING,
                    RunStatus.RESOLVING,
                    RunStatus.SUCCESS,
                    RunStatus.PARTIAL_FAILURE,
                ]
            ),
        )
    )
    latest_run_id = result.scalar_one_or_none()
    return int(latest_run_id) if latest_run_id is not None else None


def publications_query(
    *,
    user_id: int,
    mode: str,
    latest_run_id: int | None,
    scholar_profile_id: int | None,
    favorite_only: bool,
    limit: int,
    offset: int = 0,
    search: str | None = None,
    sort_by: str = "first_seen",
    sort_dir: str = "desc",
    snapshot_before: datetime | None = None,
) -> Select[tuple]:
    scholar_label = ScholarProfile.display_name
    stmt = (
        select(
            Publication.id,
            ScholarProfile.id,
            scholar_label,
            ScholarProfile.scholar_id,
            Publication.title_raw,
            Publication.year,
            Publication.citation_count,
            Publication.venue_text,
            Publication.pub_url,
            Publication.pdf_url,
            ScholarPublication.is_read,
            ScholarPublication.is_favorite,
            ScholarPublication.first_seen_run_id,
            ScholarPublication.created_at,
        )
        .join(ScholarPublication, ScholarPublication.publication_id == Publication.id)
        .join(ScholarProfile, ScholarProfile.id == ScholarPublication.scholar_profile_id)
        .outerjoin(PublicationPdfJob, PublicationPdfJob.publication_id == Publication.id)
        .where(ScholarProfile.user_id == user_id)
    )
    if search:
        safe_search = search.replace("%", r"\%").replace("_", r"\_")
        pat = f"%{safe_search}%"
        stmt = stmt.where(
            Publication.title_raw.ilike(pat)
            | ScholarProfile.display_name.ilike(pat)
            | Publication.venue_text.ilike(pat)
        )
    if scholar_profile_id is not None:
        stmt = stmt.where(ScholarProfile.id == scholar_profile_id)
    if favorite_only:
        stmt = stmt.where(ScholarPublication.is_favorite.is_(True))
    if mode == MODE_UNREAD:
        stmt = stmt.where(ScholarPublication.is_read.is_(False))
    if mode == MODE_LATEST:
        if latest_run_id is None:
            return stmt.where(sa_false())
        stmt = stmt.where(ScholarPublication.first_seen_run_id == latest_run_id)
    if snapshot_before is not None:
        stmt = stmt.where(ScholarPublication.created_at <= snapshot_before)

    sort_col = _sort_column(sort_by)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    stmt = stmt.order_by(order, Publication.id.desc())

    if limit is not None:
        stmt = stmt.offset(max(int(offset), 0)).limit(limit)

    return stmt


def publication_query_for_user(
    *,
    user_id: int,
    scholar_profile_id: int,
    publication_id: int,
) -> Select[tuple]:
    return (
        select(
            Publication.id,
            ScholarProfile.id,
            ScholarProfile.display_name,
            ScholarProfile.scholar_id,
            Publication.title_raw,
            Publication.year,
            Publication.citation_count,
            Publication.venue_text,
            Publication.pub_url,
            Publication.pdf_url,
            ScholarPublication.is_read,
            ScholarPublication.is_favorite,
            ScholarPublication.first_seen_run_id,
            ScholarPublication.created_at,
        )
        .join(ScholarPublication, ScholarPublication.publication_id == Publication.id)
        .join(ScholarProfile, ScholarProfile.id == ScholarPublication.scholar_profile_id)
        .where(
            ScholarProfile.user_id == user_id,
            ScholarProfile.id == scholar_profile_id,
            Publication.id == publication_id,
        )
        .limit(1)
    )


async def get_publication_item_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
    publication_id: int,
) -> PublicationListItem | None:
    latest_run_id = await get_latest_run_id_for_user(db_session, user_id=user_id)
    result = await db_session.execute(
        publication_query_for_user(
            user_id=user_id,
            scholar_profile_id=scholar_profile_id,
            publication_id=publication_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    return publication_list_item_from_row(row, latest_run_id=latest_run_id)


def publication_list_item_from_row(
    row: Any,
    *,
    latest_run_id: int | None,
) -> PublicationListItem:
    (
        publication_id,
        scholar_profile_id,
        display_name,
        scholar_id,
        title_raw,
        year,
        citation_count,
        venue_text,
        pub_url,
        pdf_url,
        is_read,
        is_favorite,
        first_seen_run_id,
        created_at,
    ) = row
    return PublicationListItem(
        publication_id=int(publication_id),
        scholar_profile_id=int(scholar_profile_id),
        scholar_label=(display_name or scholar_id),
        title=title_raw,
        year=year,
        citation_count=_normalized_citation_count(citation_count),
        venue_text=venue_text,
        pub_url=pub_url,
        pdf_url=pdf_url,
        is_read=bool(is_read),
        is_favorite=bool(is_favorite),
        first_seen_at=created_at,
        is_new_in_latest_run=(latest_run_id is not None and int(first_seen_run_id or 0) == latest_run_id),
    )


def unread_item_from_row(row: Any) -> UnreadPublicationItem:
    (
        publication_id,
        scholar_profile_id,
        display_name,
        scholar_id,
        title_raw,
        year,
        citation_count,
        venue_text,
        pub_url,
        pdf_url,
        _is_read,
        _is_favorite,
        _first_seen_run_id,
        _created_at,
    ) = row
    return UnreadPublicationItem(
        publication_id=int(publication_id),
        scholar_profile_id=int(scholar_profile_id),
        scholar_label=(display_name or scholar_id),
        title=title_raw,
        year=year,
        citation_count=_normalized_citation_count(citation_count),
        venue_text=venue_text,
        pub_url=pub_url,
        pdf_url=pdf_url,
    )
