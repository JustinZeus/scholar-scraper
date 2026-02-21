from __future__ import annotations

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScholarProfile, ScholarPublication


def _normalized_selection_pairs(selections: list[tuple[int, int]]) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for scholar_profile_id, publication_id in selections:
        normalized = (int(scholar_profile_id), int(publication_id))
        if normalized[0] <= 0 or normalized[1] <= 0:
            continue
        pairs.add(normalized)
    return pairs


def _scoped_scholar_ids_query(*, user_id: int):
    return (
        select(ScholarProfile.id)
        .where(ScholarProfile.user_id == user_id)
        .scalar_subquery()
    )


async def mark_all_unread_as_read_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> int:
    scholar_ids = _scoped_scholar_ids_query(user_id=user_id)
    stmt = (
        update(ScholarPublication)
        .where(
            ScholarPublication.scholar_profile_id.in_(scholar_ids),
            ScholarPublication.is_read.is_(False),
        )
        .values(is_read=True)
    )
    result = await db_session.execute(stmt)
    await db_session.commit()
    return int(result.rowcount or 0)


async def mark_selected_as_read_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    selections: list[tuple[int, int]],
) -> int:
    normalized_pairs = _normalized_selection_pairs(selections)
    if not normalized_pairs:
        return 0

    scholar_ids = _scoped_scholar_ids_query(user_id=user_id)
    stmt = (
        update(ScholarPublication)
        .where(
            ScholarPublication.scholar_profile_id.in_(scholar_ids),
            tuple_(
                ScholarPublication.scholar_profile_id,
                ScholarPublication.publication_id,
            ).in_(list(normalized_pairs)),
            ScholarPublication.is_read.is_(False),
        )
        .values(is_read=True)
    )
    result = await db_session.execute(stmt)
    await db_session.commit()
    return int(result.rowcount or 0)


async def set_publication_favorite_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
    publication_id: int,
    is_favorite: bool,
) -> int:
    scholar_ids = _scoped_scholar_ids_query(user_id=user_id)
    stmt = (
        update(ScholarPublication)
        .where(
            ScholarPublication.scholar_profile_id.in_(scholar_ids),
            ScholarPublication.scholar_profile_id == int(scholar_profile_id),
            ScholarPublication.publication_id == int(publication_id),
        )
        .values(is_favorite=bool(is_favorite))
    )
    result = await db_session.execute(stmt)
    await db_session.commit()
    return int(result.rowcount or 0)
