from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlRun, Publication, RunStatus, ScholarProfile, ScholarPublication
from app.services.domains.publications.modes import MODE_LATEST, MODE_UNREAD
from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem


def _normalized_citation_count(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def get_latest_completed_run_id_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> int | None:
    result = await db_session.execute(
        select(func.max(CrawlRun.id)).where(
            CrawlRun.user_id == user_id,
            CrawlRun.status != RunStatus.RUNNING,
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
    limit: int,
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
            ScholarPublication.first_seen_run_id,
            ScholarPublication.created_at,
        )
        .join(ScholarPublication, ScholarPublication.publication_id == Publication.id)
        .join(ScholarProfile, ScholarProfile.id == ScholarPublication.scholar_profile_id)
        .where(ScholarProfile.user_id == user_id)
        .order_by(ScholarPublication.created_at.desc(), Publication.id.desc())
        .limit(limit)
    )
    if scholar_profile_id is not None:
        stmt = stmt.where(ScholarProfile.id == scholar_profile_id)
    if mode == MODE_UNREAD:
        stmt = stmt.where(ScholarPublication.is_read.is_(False))
    if mode == MODE_LATEST:
        if latest_run_id is None:
            return stmt.where(False)
        stmt = stmt.where(ScholarPublication.first_seen_run_id == latest_run_id)
    return stmt


def publication_list_item_from_row(
    row: tuple,
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
        first_seen_at=created_at,
        is_new_in_latest_run=(
            latest_run_id is not None and int(first_seen_run_id or 0) == latest_run_id
        ),
    )


def unread_item_from_row(row: tuple) -> UnreadPublicationItem:
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
