from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    Publication,
    RunStatus,
    ScholarProfile,
    ScholarPublication,
)

MODE_ALL = "all"
MODE_UNREAD = "unread"
MODE_LATEST = "latest"
MODE_NEW = "new"  # compatibility alias for MODE_LATEST


@dataclass(frozen=True)
class PublicationListItem:
    publication_id: int
    scholar_profile_id: int
    scholar_label: str
    title: str
    year: int | None
    citation_count: int
    venue_text: str | None
    pub_url: str | None
    is_read: bool
    first_seen_at: datetime
    is_new_in_latest_run: bool


@dataclass(frozen=True)
class UnreadPublicationItem:
    publication_id: int
    scholar_profile_id: int
    scholar_label: str
    title: str
    year: int | None
    citation_count: int
    venue_text: str | None
    pub_url: str | None


def resolve_publication_view_mode(value: str | None) -> str:
    if value == MODE_UNREAD:
        return MODE_UNREAD
    if value in {MODE_LATEST, MODE_NEW}:
        return MODE_LATEST
    return MODE_ALL


def resolve_mode(value: str | None) -> str:
    return resolve_publication_view_mode(value)


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
        # "Latest" means discovered in the latest completed run.
        if latest_run_id is None:
            stmt = stmt.where(False)
        else:
            stmt = stmt.where(ScholarPublication.first_seen_run_id == latest_run_id)
    return stmt


async def list_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    mode: str = MODE_ALL,
    scholar_profile_id: int | None = None,
    limit: int = 300,
) -> list[PublicationListItem]:
    resolved_mode = resolve_publication_view_mode(mode)
    latest_run_id = await get_latest_completed_run_id_for_user(
        db_session,
        user_id=user_id,
    )
    result = await db_session.execute(
        publications_query(
            user_id=user_id,
            mode=resolved_mode,
            latest_run_id=latest_run_id,
            scholar_profile_id=scholar_profile_id,
            limit=limit,
        )
    )

    rows = result.all()
    items: list[PublicationListItem] = []
    for row in rows:
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
            is_read,
            first_seen_run_id,
            created_at,
        ) = row
        items.append(
            PublicationListItem(
                publication_id=int(publication_id),
                scholar_profile_id=int(scholar_profile_id),
                scholar_label=(display_name or scholar_id),
                title=title_raw,
                year=year,
                citation_count=int(citation_count or 0),
                venue_text=venue_text,
                pub_url=pub_url,
                is_read=bool(is_read),
                first_seen_at=created_at,
                is_new_in_latest_run=(
                    latest_run_id is not None and int(first_seen_run_id or 0) == latest_run_id
                ),
            )
        )
    return items


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
    rows = result.all()
    items: list[UnreadPublicationItem] = []
    for row in rows:
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
            _is_read,
            _first_seen_run_id,
            _created_at,
        ) = row
        items.append(
            UnreadPublicationItem(
                publication_id=int(publication_id),
                scholar_profile_id=int(scholar_profile_id),
                scholar_label=(display_name or scholar_id),
                title=title_raw,
                year=year,
                citation_count=int(citation_count or 0),
                venue_text=venue_text,
                pub_url=pub_url,
            )
        )
    return items


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
        )
        for row in rows
    ]


async def count_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    mode: str = MODE_ALL,
    scholar_profile_id: int | None = None,
) -> int:
    resolved_mode = resolve_publication_view_mode(mode)
    latest_run_id = await get_latest_completed_run_id_for_user(
        db_session,
        user_id=user_id,
    )
    stmt = (
        select(func.count())
        .select_from(ScholarPublication)
        .join(ScholarProfile, ScholarProfile.id == ScholarPublication.scholar_profile_id)
        .where(ScholarProfile.user_id == user_id)
    )
    if scholar_profile_id is not None:
        stmt = stmt.where(ScholarProfile.id == scholar_profile_id)
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
) -> int:
    return await count_for_user(
        db_session,
        user_id=user_id,
        mode=MODE_UNREAD,
        scholar_profile_id=scholar_profile_id,
    )


async def count_latest_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int | None = None,
) -> int:
    return await count_for_user(
        db_session,
        user_id=user_id,
        mode=MODE_LATEST,
        scholar_profile_id=scholar_profile_id,
    )


async def mark_all_unread_as_read_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> int:
    scholar_ids = (
        select(ScholarProfile.id)
        .where(ScholarProfile.user_id == user_id)
        .scalar_subquery()
    )

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

    rowcount = result.rowcount
    return int(rowcount or 0)


async def mark_selected_as_read_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    selections: list[tuple[int, int]],
) -> int:
    normalized_pairs = {
        (int(scholar_profile_id), int(publication_id))
        for scholar_profile_id, publication_id in selections
        if int(scholar_profile_id) > 0 and int(publication_id) > 0
    }
    if not normalized_pairs:
        return 0

    scholar_ids = (
        select(ScholarProfile.id)
        .where(ScholarProfile.user_id == user_id)
        .scalar_subquery()
    )
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
