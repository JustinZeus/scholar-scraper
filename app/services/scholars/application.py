from __future__ import annotations

import os
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScholarProfile
from app.services.scholar.parser import ScholarParserError, parse_profile_page
from app.services.scholar.source import ScholarSource
from app.services.scholars.author_search import search_author_candidates
from app.services.scholars.constants import (
    ALLOWED_IMAGE_UPLOAD_CONTENT_TYPES,
    SEARCH_COOLDOWN_REASON,
    SEARCH_DISABLED_REASON,
)
from app.services.scholars.exceptions import ScholarServiceError
from app.services.scholars.uploads import (
    _ensure_upload_root,
    _resolve_upload_path,
    _safe_remove_upload,
)
from app.services.scholars.validators import (
    normalize_display_name,
    normalize_profile_image_url,
    validate_scholar_id,
)

__all__ = [
    "SEARCH_COOLDOWN_REASON",
    "SEARCH_DISABLED_REASON",
    "ScholarServiceError",
    "clear_profile_image_customization",
    "create_scholar_for_user",
    "delete_scholar",
    "get_user_scholar_by_id",
    "hydrate_profile_metadata",
    "list_scholars_for_user",
    "normalize_display_name",
    "normalize_profile_image_url",
    "search_author_candidates",
    "set_profile_image_override_url",
    "set_profile_image_upload",
    "toggle_scholar_enabled",
    "validate_scholar_id",
]


async def list_scholars_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> list[ScholarProfile]:
    from sqlalchemy import select

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
    profile_image_url: str | None = None,
) -> ScholarProfile:
    profile = ScholarProfile(
        user_id=user_id,
        scholar_id=validate_scholar_id(scholar_id),
        display_name=normalize_display_name(display_name),
        profile_image_url=normalize_profile_image_url(profile_image_url),
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
    from sqlalchemy import select

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
    upload_dir: str | None = None,
) -> None:
    if upload_dir:
        upload_root = _ensure_upload_root(upload_dir, create=True)
        _safe_remove_upload(upload_root, profile.profile_image_upload_path)

    await db_session.delete(profile)
    await db_session.commit()


async def hydrate_profile_metadata(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    source: ScholarSource,
) -> ScholarProfile:
    fetch_result = await source.fetch_profile_html(profile.scholar_id)
    try:
        parsed_page = parse_profile_page(fetch_result)
    except ScholarParserError:
        return profile

    if parsed_page.profile_name and not (profile.display_name or "").strip():
        profile.display_name = parsed_page.profile_name
    if parsed_page.profile_image_url and not profile.profile_image_url:
        profile.profile_image_url = parsed_page.profile_image_url

    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def set_profile_image_override_url(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    image_url: str | None,
    upload_dir: str,
) -> ScholarProfile:
    upload_root = _ensure_upload_root(upload_dir, create=True)
    _safe_remove_upload(upload_root, profile.profile_image_upload_path)

    profile.profile_image_upload_path = None
    profile.profile_image_override_url = normalize_profile_image_url(image_url)

    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def clear_profile_image_customization(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    upload_dir: str,
) -> ScholarProfile:
    upload_root = _ensure_upload_root(upload_dir, create=True)
    _safe_remove_upload(upload_root, profile.profile_image_upload_path)

    profile.profile_image_upload_path = None
    profile.profile_image_override_url = None

    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def set_profile_image_upload(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    content_type: str | None,
    image_bytes: bytes,
    upload_dir: str,
    max_upload_bytes: int,
) -> ScholarProfile:
    normalized_content_type = (content_type or "").strip().lower()
    extension = ALLOWED_IMAGE_UPLOAD_CONTENT_TYPES.get(normalized_content_type)
    if extension is None:
        raise ScholarServiceError("Unsupported image type. Use JPEG, PNG, WEBP, or GIF.")

    if not image_bytes:
        raise ScholarServiceError("Uploaded image file is empty.")

    if len(image_bytes) > max_upload_bytes:
        raise ScholarServiceError(f"Uploaded image exceeds {max_upload_bytes} bytes.")

    upload_root = _ensure_upload_root(upload_dir, create=True)
    user_dir = upload_root / str(profile.user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{profile.id}_{uuid4().hex}{extension}"
    relative_path = os.path.join(str(profile.user_id), filename)
    absolute_path = _resolve_upload_path(upload_root, relative_path)
    absolute_path.write_bytes(image_bytes)

    old_path = profile.profile_image_upload_path
    profile.profile_image_upload_path = relative_path
    profile.profile_image_override_url = None

    await db_session.commit()
    await db_session.refresh(profile)

    if old_path and old_path != relative_path:
        _safe_remove_upload(upload_root, old_path)

    return profile
