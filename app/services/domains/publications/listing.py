from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domains.publications.modes import (
    MODE_ALL,
    MODE_LATEST,
    MODE_UNREAD,
    resolve_publication_view_mode,
)
from app.services.domains.publications.queries import (
    get_latest_completed_run_id_for_user,
    get_publication_item_for_user,
    publication_list_item_from_row,
    publications_query,
    unread_item_from_row,
)
from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem
from app.services.domains.unpaywall.application import resolve_publication_oa_metadata
from sqlalchemy import update
from app.db.models import Publication


def _with_oa_overrides(
    rows: list[PublicationListItem],
    oa_data: dict[int, tuple[str | None, str | None]],
) -> list[PublicationListItem]:
    return [
        PublicationListItem(
            publication_id=row.publication_id,
            scholar_profile_id=row.scholar_profile_id,
            scholar_label=row.scholar_label,
            title=row.title,
            year=row.year,
            citation_count=row.citation_count,
            venue_text=row.venue_text,
            pub_url=row.pub_url,
            doi=(oa_data.get(row.publication_id) or (None, None))[0] or row.doi,
            pdf_url=(oa_data.get(row.publication_id) or (None, None))[1] or row.pdf_url,
            is_read=row.is_read,
            first_seen_at=row.first_seen_at,
            is_new_in_latest_run=row.is_new_in_latest_run,
        )
        for row in rows
    ]


def _resolved_fields(
    *,
    row: PublicationListItem,
    resolved: tuple[str | None, str | None] | None,
) -> tuple[str | None, str | None]:
    if resolved is None:
        return row.doi, row.pdf_url
    resolved_doi, resolved_pdf = resolved
    return resolved_doi or row.doi, resolved_pdf or row.pdf_url


async def _persist_resolved_metadata(
    db_session: AsyncSession,
    *,
    rows: list[PublicationListItem],
    oa_data: dict[int, tuple[str | None, str | None]],
) -> None:
    by_id = {row.publication_id: row for row in rows}
    updates: list[tuple[int, str | None, str | None]] = []
    for publication_id, resolved in oa_data.items():
        existing = by_id.get(publication_id)
        if existing is None:
            continue
        next_doi, next_pdf = _resolved_fields(row=existing, resolved=resolved)
        if next_doi == existing.doi and next_pdf == existing.pdf_url:
            continue
        updates.append((publication_id, next_doi, next_pdf))
    for publication_id, doi, pdf_url in updates:
        await db_session.execute(
            update(Publication)
            .where(Publication.id == publication_id)
            .values(doi=doi, pdf_url=pdf_url)
        )
    if updates:
        await db_session.commit()


def missing_pdf_items(
    rows: list[PublicationListItem],
    *,
    limit: int,
) -> list[PublicationListItem]:
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    return [row for row in rows if not row.pdf_url][:bounded_limit]


async def resolve_and_persist_oa_metadata(
    db_session: AsyncSession,
    *,
    rows: list[PublicationListItem],
    unpaywall_email: str | None = None,
) -> dict[int, tuple[str | None, str | None]]:
    if not rows:
        return {}
    oa_data = await resolve_publication_oa_metadata(rows, request_email=unpaywall_email)
    await _persist_resolved_metadata(db_session, rows=rows, oa_data=oa_data)
    return oa_data


async def list_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    mode: str = MODE_ALL,
    scholar_profile_id: int | None = None,
    limit: int = 300,
) -> list[PublicationListItem]:
    resolved_mode = resolve_publication_view_mode(mode)
    latest_run_id = await get_latest_completed_run_id_for_user(db_session, user_id=user_id)
    result = await db_session.execute(
        publications_query(
            user_id=user_id,
            mode=resolved_mode,
            latest_run_id=latest_run_id,
            scholar_profile_id=scholar_profile_id,
            limit=limit,
        )
    )
    rows = [
        publication_list_item_from_row(row, latest_run_id=latest_run_id)
        for row in result.all()
    ]
    return rows


async def retry_pdf_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
    publication_id: int,
    unpaywall_email: str | None = None,
) -> PublicationListItem | None:
    item = await get_publication_item_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
    if item is None:
        return None
    oa_data = await resolve_and_persist_oa_metadata(
        db_session,
        rows=[item],
        unpaywall_email=unpaywall_email,
    )
    return _with_oa_overrides([item], oa_data)[0]


async def list_unread_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
) -> list[UnreadPublicationItem]:
    result = await db_session.execute(
        publications_query(
            user_id=user_id,
            mode=MODE_UNREAD,
            latest_run_id=None,
            scholar_profile_id=None,
            limit=limit,
        )
    )
    return [unread_item_from_row(row) for row in result.all()]


async def list_new_for_latest_run_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
) -> list[UnreadPublicationItem]:
    rows = await list_for_user(
        db_session,
        user_id=user_id,
        mode=MODE_LATEST,
        scholar_profile_id=None,
        limit=limit,
    )
    return [_to_unread_item(row) for row in rows]


def _to_unread_item(row: PublicationListItem) -> UnreadPublicationItem:
    return UnreadPublicationItem(
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
    )
