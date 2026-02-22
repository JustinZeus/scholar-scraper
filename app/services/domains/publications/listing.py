from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domains.publication_identifiers import application as identifier_service
from app.services.domains.publications.modes import (
    MODE_ALL,
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


async def list_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    mode: str = MODE_ALL,
    scholar_profile_id: int | None = None,
    favorite_only: bool = False,
    limit: int = 300,
    offset: int = 0,
) -> list[PublicationListItem]:
    resolved_mode = resolve_publication_view_mode(mode)
    latest_run_id = await get_latest_completed_run_id_for_user(db_session, user_id=user_id)
    result = await db_session.execute(
        publications_query(
            user_id=user_id,
            mode=resolved_mode,
            latest_run_id=latest_run_id,
            scholar_profile_id=scholar_profile_id,
            favorite_only=favorite_only,
            limit=limit,
            offset=offset,
        )
    )
    rows = [
        publication_list_item_from_row(row, latest_run_id=latest_run_id)
        for row in result.all()
    ]
    return await identifier_service.overlay_publication_items_with_display_identifiers(
        db_session,
        items=rows,
    )


async def retry_pdf_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
    publication_id: int,
) -> PublicationListItem | None:
    item = await get_publication_item_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
    if item is None:
        return None
    hydrated = await identifier_service.overlay_publication_items_with_display_identifiers(
        db_session,
        items=[item],
    )
    return hydrated[0] if hydrated else item


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
            favorite_only=False,
            limit=limit,
            offset=0,
        )
    )
    return [unread_item_from_row(row) for row in result.all()]
