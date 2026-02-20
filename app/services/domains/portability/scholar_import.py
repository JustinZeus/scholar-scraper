from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScholarProfile
from app.services.domains.portability.normalize import _normalize_optional_text
from app.services.domains.scholars import application as scholar_service


async def _load_user_scholar_map(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> dict[str, ScholarProfile]:
    result = await db_session.execute(
        select(ScholarProfile).where(ScholarProfile.user_id == user_id)
    )
    profiles = list(result.scalars().all())
    return {profile.scholar_id: profile for profile in profiles}


def _apply_imported_scholar_values(
    *,
    profile: ScholarProfile,
    display_name: str | None,
    profile_image_override_url: str | None,
    is_enabled: bool,
) -> bool:
    updated = False
    if display_name and profile.display_name != display_name:
        profile.display_name = display_name
        updated = True
    if profile.profile_image_override_url != profile_image_override_url:
        profile.profile_image_override_url = profile_image_override_url
        updated = True
    if bool(profile.is_enabled) != bool(is_enabled):
        profile.is_enabled = bool(is_enabled)
        updated = True
    return updated


def _new_scholar_profile(
    *,
    user_id: int,
    scholar_id: str,
    display_name: str | None,
    profile_image_override_url: str | None,
    is_enabled: bool,
) -> ScholarProfile:
    return ScholarProfile(
        user_id=user_id,
        scholar_id=scholar_id,
        display_name=display_name,
        profile_image_override_url=profile_image_override_url,
        is_enabled=bool(is_enabled),
    )


async def _upsert_imported_scholars(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholars: list[dict[str, Any]],
) -> tuple[dict[str, ScholarProfile], dict[str, int]]:
    scholar_map = await _load_user_scholar_map(db_session, user_id=user_id)
    counters = {"scholars_created": 0, "scholars_updated": 0, "skipped_records": 0}
    for item in scholars:
        try:
            scholar_id = scholar_service.validate_scholar_id(str(item["scholar_id"]))
            display_name = scholar_service.normalize_display_name(
                str(item.get("display_name") or "")
            )
            override_url = scholar_service.normalize_profile_image_url(
                _normalize_optional_text(item.get("profile_image_override_url"))
            )
        except (KeyError, scholar_service.ScholarServiceError):
            counters["skipped_records"] += 1
            continue

        is_enabled = bool(item.get("is_enabled", True))
        existing = scholar_map.get(scholar_id)
        if existing is None:
            profile = _new_scholar_profile(
                user_id=user_id,
                scholar_id=scholar_id,
                display_name=display_name,
                profile_image_override_url=override_url,
                is_enabled=is_enabled,
            )
            db_session.add(profile)
            scholar_map[scholar_id] = profile
            counters["scholars_created"] += 1
            continue

        if _apply_imported_scholar_values(
            profile=existing,
            display_name=display_name,
            profile_image_override_url=override_url,
            is_enabled=is_enabled,
        ):
            counters["scholars_updated"] += 1

    await db_session.flush()
    return scholar_map, counters
