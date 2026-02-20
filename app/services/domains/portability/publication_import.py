from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication, ScholarProfile, ScholarPublication
from app.services.domains.ingestion.application import build_publication_url, normalize_title
from app.services.domains.doi.normalize import normalize_doi
from app.services.domains.portability.normalize import (
    _normalize_citation_count,
    _normalize_optional_text,
    _normalize_optional_year,
    _resolve_fingerprint,
)
from app.services.domains.portability.types import ImportedPublicationInput


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


async def _find_linked_publication_by_title(
    db_session: AsyncSession,
    *,
    scholar_profile_id: int,
    title: str,
) -> Publication | None:
    normalized_title = normalize_title(title)
    result = await db_session.execute(
        select(Publication)
        .join(
            ScholarPublication,
            ScholarPublication.publication_id == Publication.id,
        )
        .where(
            ScholarPublication.scholar_profile_id == scholar_profile_id,
            Publication.title_normalized == normalized_title,
        )
        .order_by(Publication.id.asc())
        .limit(1)
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
    doi: str | None,
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
    if doi and publication.doi != doi:
        publication.doi = doi
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
    doi: str | None,
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
        doi=doi,
        pdf_url=pdf_url,
    )


async def _resolve_publication_for_import(
    db_session: AsyncSession,
    *,
    scholar_profile_id: int,
    title: str,
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
    if fingerprint_cache[fingerprint_sha256] is not None:
        return fingerprint_cache[fingerprint_sha256]
    return await _find_linked_publication_by_title(
        db_session,
        scholar_profile_id=scholar_profile_id,
        title=title,
    )


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
        doi=normalize_doi(_normalize_optional_text(item.get("doi"))),
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
        doi=payload.doi,
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
        doi=payload.doi,
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
        scholar_profile_id=int(payload.profile.id),
        title=payload.title,
        cluster_id=payload.cluster_id,
        fingerprint_sha256=payload.fingerprint,
        cluster_cache=cluster_cache,
        fingerprint_cache=fingerprint_cache,
    )
    created = False
    updated = False
    if publication is None:
        publication = await _create_import_publication(db_session, payload=payload)
        created = True
    else:
        updated = _update_import_publication(publication=publication, payload=payload)

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
