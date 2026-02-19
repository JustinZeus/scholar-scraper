from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication, ScholarProfile, ScholarPublication
from app.services import scholars as scholar_service
from app.services.ingestion import build_publication_url, normalize_title

EXPORT_SCHEMA_VERSION = 1
MAX_IMPORT_SCHOLARS = 10_000
MAX_IMPORT_PUBLICATIONS = 100_000
WORD_RE = re.compile(r"[a-z0-9]+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ImportExportError(ValueError):
    """Raised when import/export payload constraints are violated."""


@dataclass(frozen=True)
class ImportedPublicationInput:
    profile: ScholarProfile
    title: str
    year: int | None
    citation_count: int
    author_text: str | None
    venue_text: str | None
    cluster_id: str | None
    pub_url: str | None
    pdf_url: str | None
    fingerprint: str
    is_read: bool


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_optional_year(value: Any) -> int | None:
    if value is None:
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if year < 1500 or year > 3000:
        return None
    return year


def _normalize_citation_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _first_author_last_name(authors_text: str | None) -> str:
    if not authors_text:
        return ""
    first_author = authors_text.split(",", maxsplit=1)[0].strip().lower()
    words = WORD_RE.findall(first_author)
    if not words:
        return ""
    return words[-1]


def _first_venue_word(venue_text: str | None) -> str:
    if not venue_text:
        return ""
    words = WORD_RE.findall(venue_text.lower())
    if not words:
        return ""
    return words[0]


def _build_fingerprint(
    *,
    title: str,
    year: int | None,
    author_text: str | None,
    venue_text: str | None,
) -> str:
    canonical = "|".join(
        [
            normalize_title(title),
            str(year) if year is not None else "",
            _first_author_last_name(author_text),
            _first_venue_word(venue_text),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_fingerprint(
    *,
    title: str,
    year: int | None,
    author_text: str | None,
    venue_text: str | None,
    provided_fingerprint: Any,
) -> str:
    normalized = _normalize_optional_text(provided_fingerprint)
    if normalized and SHA256_RE.fullmatch(normalized.lower()):
        return normalized.lower()
    return _build_fingerprint(
        title=title,
        year=year,
        author_text=author_text,
        venue_text=venue_text,
    )


def _validate_import_sizes(
    *,
    scholars: list[dict[str, Any]],
    publications: list[dict[str, Any]],
) -> None:
    if len(scholars) > MAX_IMPORT_SCHOLARS:
        raise ImportExportError(f"Import exceeds max scholars ({MAX_IMPORT_SCHOLARS}).")
    if len(publications) > MAX_IMPORT_PUBLICATIONS:
        raise ImportExportError(
            f"Import exceeds max publications ({MAX_IMPORT_PUBLICATIONS})."
        )


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
            display_name = scholar_service.normalize_display_name(str(item.get("display_name") or ""))
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


async def _find_publication_by_cluster(
    db_session: AsyncSession,
    *,
    cluster_id: str,
) -> Publication | None:
    result = await db_session.execute(
        select(Publication).where(Publication.cluster_id == cluster_id)
    )
    return result.scalar_one_or_none()


async def _find_publication_by_fingerprint(
    db_session: AsyncSession,
    *,
    fingerprint_sha256: str,
) -> Publication | None:
    result = await db_session.execute(
        select(Publication).where(Publication.fingerprint_sha256 == fingerprint_sha256)
    )
    return result.scalar_one_or_none()


def _apply_imported_publication_values(
    *,
    publication: Publication,
    title: str,
    year: int | None,
    citation_count: int,
    author_text: str | None,
    venue_text: str | None,
    pub_url: str | None,
    pdf_url: str | None,
    cluster_id: str | None,
) -> bool:
    updated = False
    if cluster_id and publication.cluster_id != cluster_id:
        publication.cluster_id = cluster_id
        updated = True
    if publication.title_raw != title:
        publication.title_raw = title
        publication.title_normalized = normalize_title(title)
        updated = True
    if publication.year != year:
        publication.year = year
        updated = True
    if int(publication.citation_count or 0) != citation_count:
        publication.citation_count = citation_count
        updated = True
    if publication.author_text != author_text:
        publication.author_text = author_text
        updated = True
    if publication.venue_text != venue_text:
        publication.venue_text = venue_text
        updated = True
    if pub_url and publication.pub_url != pub_url:
        publication.pub_url = pub_url
        updated = True
    if pdf_url and publication.pdf_url != pdf_url:
        publication.pdf_url = pdf_url
        updated = True
    return updated


def _new_publication(
    *,
    cluster_id: str | None,
    fingerprint_sha256: str,
    title: str,
    year: int | None,
    citation_count: int,
    author_text: str | None,
    venue_text: str | None,
    pub_url: str | None,
    pdf_url: str | None,
) -> Publication:
    return Publication(
        cluster_id=cluster_id,
        fingerprint_sha256=fingerprint_sha256,
        title_raw=title,
        title_normalized=normalize_title(title),
        year=year,
        citation_count=citation_count,
        author_text=author_text,
        venue_text=venue_text,
        pub_url=pub_url,
        pdf_url=pdf_url,
    )


async def _resolve_publication_for_import(
    db_session: AsyncSession,
    *,
    cluster_id: str | None,
    fingerprint_sha256: str,
    cluster_cache: dict[str, Publication | None],
    fingerprint_cache: dict[str, Publication | None],
) -> Publication | None:
    if cluster_id:
        if cluster_id not in cluster_cache:
            cluster_cache[cluster_id] = await _find_publication_by_cluster(
                db_session,
                cluster_id=cluster_id,
            )
        if cluster_cache[cluster_id] is not None:
            return cluster_cache[cluster_id]
    if fingerprint_sha256 not in fingerprint_cache:
        fingerprint_cache[fingerprint_sha256] = await _find_publication_by_fingerprint(
            db_session,
            fingerprint_sha256=fingerprint_sha256,
        )
    return fingerprint_cache[fingerprint_sha256]


async def _upsert_scholar_publication_link(
    db_session: AsyncSession,
    *,
    scholar_profile_id: int,
    publication_id: int,
    is_read: bool,
) -> tuple[bool, bool]:
    result = await db_session.execute(
        select(ScholarPublication).where(
            ScholarPublication.scholar_profile_id == scholar_profile_id,
            ScholarPublication.publication_id == publication_id,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        db_session.add(
            ScholarPublication(
                scholar_profile_id=scholar_profile_id,
                publication_id=publication_id,
                is_read=bool(is_read),
            )
        )
        return True, False
    if bool(link.is_read) == bool(is_read):
        return False, False
    link.is_read = bool(is_read)
    return False, True


def _initialize_import_counters(counters: dict[str, int]) -> None:
    counters.update(
        {
            "publications_created": 0,
            "publications_updated": 0,
            "links_created": 0,
            "links_updated": 0,
        }
    )


def _build_imported_publication_input(
    *,
    item: dict[str, Any],
    scholar_map: dict[str, ScholarProfile],
) -> ImportedPublicationInput | None:
    scholar_id = _normalize_optional_text(item.get("scholar_id"))
    title = _normalize_optional_text(item.get("title"))
    if not scholar_id or not title:
        return None
    profile = scholar_map.get(scholar_id)
    if profile is None:
        return None
    year = _normalize_optional_year(item.get("year"))
    author_text = _normalize_optional_text(item.get("author_text"))
    venue_text = _normalize_optional_text(item.get("venue_text"))
    return ImportedPublicationInput(
        profile=profile,
        title=title,
        year=year,
        citation_count=_normalize_citation_count(item.get("citation_count")),
        author_text=author_text,
        venue_text=venue_text,
        cluster_id=_normalize_optional_text(item.get("cluster_id")),
        pub_url=build_publication_url(_normalize_optional_text(item.get("pub_url"))),
        pdf_url=build_publication_url(_normalize_optional_text(item.get("pdf_url"))),
        fingerprint=_resolve_fingerprint(
            title=title,
            year=year,
            author_text=author_text,
            venue_text=venue_text,
            provided_fingerprint=item.get("fingerprint_sha256"),
        ),
        is_read=bool(item.get("is_read", False)),
    )


def _update_link_counters(
    *,
    counters: dict[str, int],
    link_created: bool,
    link_updated: bool,
) -> None:
    if link_created:
        counters["links_created"] += 1
    if link_updated:
        counters["links_updated"] += 1


def _cache_resolved_publication(
    *,
    publication: Publication,
    cluster_id: str | None,
    fingerprint_sha256: str,
    cluster_cache: dict[str, Publication | None],
    fingerprint_cache: dict[str, Publication | None],
) -> None:
    if cluster_id:
        cluster_cache[cluster_id] = publication
    fingerprint_cache[fingerprint_sha256] = publication


async def _create_import_publication(
    db_session: AsyncSession,
    *,
    payload: ImportedPublicationInput,
) -> Publication:
    publication = _new_publication(
        cluster_id=payload.cluster_id,
        fingerprint_sha256=payload.fingerprint,
        title=payload.title,
        year=payload.year,
        citation_count=payload.citation_count,
        author_text=payload.author_text,
        venue_text=payload.venue_text,
        pub_url=payload.pub_url,
        pdf_url=payload.pdf_url,
    )
    db_session.add(publication)
    await db_session.flush()
    return publication


def _update_import_publication(
    *,
    publication: Publication,
    payload: ImportedPublicationInput,
) -> bool:
    return _apply_imported_publication_values(
        publication=publication,
        title=payload.title,
        year=payload.year,
        citation_count=payload.citation_count,
        author_text=payload.author_text,
        venue_text=payload.venue_text,
        pub_url=payload.pub_url,
        pdf_url=payload.pdf_url,
        cluster_id=payload.cluster_id,
    )


async def _upsert_publication_entity(
    db_session: AsyncSession,
    *,
    payload: ImportedPublicationInput,
    cluster_cache: dict[str, Publication | None],
    fingerprint_cache: dict[str, Publication | None],
) -> tuple[Publication, bool, bool]:
    publication = await _resolve_publication_for_import(
        db_session,
        cluster_id=payload.cluster_id,
        fingerprint_sha256=payload.fingerprint,
        cluster_cache=cluster_cache,
        fingerprint_cache=fingerprint_cache,
    )
    created = False
    updated = False
    if publication is None:
        publication = await _create_import_publication(
            db_session,
            payload=payload,
        )
        created = True
    else:
        updated = _update_import_publication(
            publication=publication,
            payload=payload,
        )
    _cache_resolved_publication(
        publication=publication,
        cluster_id=payload.cluster_id,
        fingerprint_sha256=payload.fingerprint,
        cluster_cache=cluster_cache,
        fingerprint_cache=fingerprint_cache,
    )
    return publication, created, updated


async def _upsert_imported_publication(
    db_session: AsyncSession,
    *,
    payload: ImportedPublicationInput,
    cluster_cache: dict[str, Publication | None],
    fingerprint_cache: dict[str, Publication | None],
    counters: dict[str, int],
) -> None:
    publication, created, updated = await _upsert_publication_entity(
        db_session,
        payload=payload,
        cluster_cache=cluster_cache,
        fingerprint_cache=fingerprint_cache,
    )
    if created:
        counters["publications_created"] += 1
    if updated:
        counters["publications_updated"] += 1
    link_created, link_updated = await _upsert_scholar_publication_link(
        db_session,
        scholar_profile_id=int(payload.profile.id),
        publication_id=int(publication.id),
        is_read=payload.is_read,
    )
    _update_link_counters(
        counters=counters,
        link_created=link_created,
        link_updated=link_updated,
    )


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
    publications = [
        _serialize_export_publication(row)
        for row in publication_result.all()
    ]
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": _exported_at_iso(),
        "scholars": scholars,
        "publications": publications,
    }


async def import_user_data(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholars: list[dict[str, Any]],
    publications: list[dict[str, Any]],
) -> dict[str, int]:
    _validate_import_sizes(scholars=scholars, publications=publications)
    scholar_map, counters = await _upsert_imported_scholars(
        db_session,
        user_id=user_id,
        scholars=scholars,
    )
    cluster_cache: dict[str, Publication | None] = {}
    fingerprint_cache: dict[str, Publication | None] = {}
    _initialize_import_counters(counters)
    for item in publications:
        parsed_item = _build_imported_publication_input(
            item=item,
            scholar_map=scholar_map,
        )
        if parsed_item is None:
            counters["skipped_records"] += 1
            continue
        await _upsert_imported_publication(
            db_session,
            payload=parsed_item,
            cluster_cache=cluster_cache,
            fingerprint_cache=fingerprint_cache,
            counters=counters,
        )
    await db_session.commit()
    return counters
