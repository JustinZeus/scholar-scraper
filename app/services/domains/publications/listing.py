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
    publication_list_item_from_row,
    publications_query,
    unread_item_from_row,
)
from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem


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
    return [
        publication_list_item_from_row(row, latest_run_id=latest_run_id)
        for row in result.all()
    ]


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
    return [
        UnreadPublicationItem(
            publication_id=row.publication_id,
            scholar_profile_id=row.scholar_profile_id,
            scholar_label=row.scholar_label,
            title=row.title,
            year=row.year,
            citation_count=row.citation_count,
            venue_text=row.venue_text,
            pub_url=row.pub_url,
            pdf_url=row.pdf_url,
        )
        for row in rows
    ]
