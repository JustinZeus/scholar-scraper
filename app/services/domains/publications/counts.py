from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScholarProfile, ScholarPublication
from app.services.domains.publications.modes import (
    MODE_ALL,
    MODE_LATEST,
    MODE_UNREAD,
    resolve_publication_view_mode,
)
from app.services.domains.publications.queries import get_latest_completed_run_id_for_user


async def count_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    mode: str = MODE_ALL,
    scholar_profile_id: int | None = None,
    favorite_only: bool = False,
) -> int:
    resolved_mode = resolve_publication_view_mode(mode)
    latest_run_id = await get_latest_completed_run_id_for_user(db_session, user_id=user_id)
    stmt = (
        select(func.count())
        .select_from(ScholarPublication)
        .join(ScholarProfile, ScholarProfile.id == ScholarPublication.scholar_profile_id)
        .where(ScholarProfile.user_id == user_id)
    )
    if scholar_profile_id is not None:
        stmt = stmt.where(ScholarProfile.id == scholar_profile_id)
    if favorite_only:
        stmt = stmt.where(ScholarPublication.is_favorite.is_(True))
    if resolved_mode == MODE_UNREAD:
        stmt = stmt.where(ScholarPublication.is_read.is_(False))
    if resolved_mode == MODE_LATEST:
        if latest_run_id is None:
            return 0
        stmt = stmt.where(ScholarPublication.first_seen_run_id == latest_run_id)
    result = await db_session.execute(stmt)
    return int(result.scalar_one() or 0)


async def count_unread_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int | None = None,
    favorite_only: bool = False,
) -> int:
    return await count_for_user(
        db_session,
        user_id=user_id,
        mode=MODE_UNREAD,
        scholar_profile_id=scholar_profile_id,
        favorite_only=favorite_only,
    )


async def count_latest_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int | None = None,
    favorite_only: bool = False,
) -> int:
    return await count_for_user(
        db_session,
        user_id=user_id,
        mode=MODE_LATEST,
        scholar_profile_id=scholar_profile_id,
        favorite_only=favorite_only,
    )


async def count_favorite_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int | None = None,
) -> int:
    return await count_for_user(
        db_session,
        user_id=user_id,
        mode=MODE_ALL,
        scholar_profile_id=scholar_profile_id,
        favorite_only=True,
    )
