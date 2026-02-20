from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication, ScholarProfile, ScholarPublication
from app.services.domains.portability.constants import EXPORT_SCHEMA_VERSION


def _exported_at_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _serialize_export_scholar(profile: ScholarProfile) -> dict[str, Any]:
    return {
        "scholar_id": profile.scholar_id,
        "display_name": profile.display_name,
        "is_enabled": bool(profile.is_enabled),
        "profile_image_override_url": profile.profile_image_override_url,
    }


def _serialize_export_publication(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        scholar_id,
        cluster_id,
        fingerprint_sha256,
        title_raw,
        year,
        citation_count,
        author_text,
        venue_text,
        pub_url,
        pdf_url,
        is_read,
    ) = row
    return {
        "scholar_id": scholar_id,
        "cluster_id": cluster_id,
        "fingerprint_sha256": fingerprint_sha256,
        "title": title_raw,
        "year": year,
        "citation_count": int(citation_count or 0),
        "author_text": author_text,
        "venue_text": venue_text,
        "pub_url": pub_url,
        "pdf_url": pdf_url,
        "is_read": bool(is_read),
    }


async def export_user_data(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> dict[str, Any]:
    scholars_result = await db_session.execute(
        select(ScholarProfile)
        .where(ScholarProfile.user_id == user_id)
        .order_by(ScholarProfile.id.asc())
    )
    publication_result = await db_session.execute(
        select(
            ScholarProfile.scholar_id,
            Publication.cluster_id,
            Publication.fingerprint_sha256,
            Publication.title_raw,
            Publication.year,
            Publication.citation_count,
            Publication.author_text,
            Publication.venue_text,
            Publication.pub_url,
            Publication.pdf_url,
            ScholarPublication.is_read,
        )
        .join(ScholarPublication, ScholarPublication.scholar_profile_id == ScholarProfile.id)
        .join(Publication, Publication.id == ScholarPublication.publication_id)
        .where(ScholarProfile.user_id == user_id)
        .order_by(ScholarPublication.created_at.desc(), Publication.id.desc())
    )
    scholars = [_serialize_export_scholar(profile) for profile in scholars_result.scalars().all()]
    publications = [_serialize_export_publication(row) for row in publication_result.all()]
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": _exported_at_iso(),
        "scholars": scholars,
        "publications": publications,
    }
