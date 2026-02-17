from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScholarProfile

SCHOLAR_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{12}$")


class ScholarServiceError(ValueError):
    """Raised for expected scholar-management validation failures."""


def validate_scholar_id(value: str) -> str:
    scholar_id = value.strip()
    if not SCHOLAR_ID_PATTERN.fullmatch(scholar_id):
        raise ScholarServiceError("Scholar ID must match [a-zA-Z0-9_-]{12}.")
    return scholar_id


def normalize_display_name(value: str) -> str | None:
    normalized = value.strip()
    return normalized if normalized else None


async def list_scholars_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> list[ScholarProfile]:
    result = await db_session.execute(
        select(ScholarProfile)
        .where(ScholarProfile.user_id == user_id)
        .order_by(ScholarProfile.created_at.desc(), ScholarProfile.id.desc())
    )
    return list(result.scalars().all())


async def create_scholar_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_id: str,
    display_name: str,
) -> ScholarProfile:
    profile = ScholarProfile(
        user_id=user_id,
        scholar_id=validate_scholar_id(scholar_id),
        display_name=normalize_display_name(display_name),
    )
    db_session.add(profile)
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise ScholarServiceError("That scholar is already tracked for this account.") from exc
    await db_session.refresh(profile)
    return profile


async def get_user_scholar_by_id(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
) -> ScholarProfile | None:
    result = await db_session.execute(
        select(ScholarProfile).where(
            ScholarProfile.id == scholar_profile_id,
            ScholarProfile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def toggle_scholar_enabled(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
) -> ScholarProfile:
    profile.is_enabled = not profile.is_enabled
    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def delete_scholar(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
) -> None:
    await db_session.delete(profile)
    await db_session.commit()

