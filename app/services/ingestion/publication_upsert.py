from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlRun, Publication, ScholarProfile, ScholarPublication
from app.services.ingestion.fingerprints import (
    build_publication_fingerprint,
    build_publication_url,
    canonical_title_for_dedup,
    normalize_title,
)
from app.services.publication_identifiers import application as identifier_service
from app.services.runs.events import run_events
from app.services.scholar.parser import PublicationCandidate

logger = logging.getLogger(__name__)


def validate_publication_candidate(candidate: PublicationCandidate) -> None:
    if not candidate.title.strip():
        raise RuntimeError("Publication candidate is missing title.")
    if candidate.citation_count is not None and int(candidate.citation_count) < 0:
        raise RuntimeError("Publication candidate has negative citation_count.")


async def find_publication_by_cluster(
    db_session: AsyncSession,
    *,
    cluster_id: str | None,
) -> Publication | None:
    if not cluster_id:
        return None
    result = await db_session.execute(select(Publication).where(Publication.cluster_id == cluster_id))
    return result.scalar_one_or_none()


async def find_publication_by_fingerprint(
    db_session: AsyncSession,
    *,
    fingerprint: str,
) -> Publication | None:
    result = await db_session.execute(select(Publication).where(Publication.fingerprint_sha256 == fingerprint))
    return result.scalar_one_or_none()


def select_existing_publication(
    *,
    cluster_publication: Publication | None,
    fingerprint_publication: Publication | None,
) -> Publication | None:
    if cluster_publication is not None:
        return cluster_publication
    return fingerprint_publication


def compute_canonical_title_hash(title: str) -> str:
    canonical = canonical_title_for_dedup(title)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def find_publication_by_canonical_title_hash(
    db_session: AsyncSession,
    *,
    canonical_title_hash: str,
) -> Publication | None:
    result = await db_session.execute(
        select(Publication).where(Publication.canonical_title_hash == canonical_title_hash)
    )
    return result.scalar_one_or_none()


async def create_publication(
    db_session: AsyncSession,
    *,
    candidate: PublicationCandidate,
    fingerprint: str,
) -> Publication:
    publication = Publication(
        cluster_id=candidate.cluster_id,
        fingerprint_sha256=fingerprint,
        title_raw=candidate.title,
        title_normalized=normalize_title(candidate.title),
        canonical_title_hash=compute_canonical_title_hash(candidate.title),
        year=candidate.year,
        citation_count=int(candidate.citation_count or 0),
        author_text=candidate.authors_text,
        venue_text=candidate.venue_text,
        pub_url=build_publication_url(candidate.title_url),
        pdf_url=None,
    )
    db_session.add(publication)
    await db_session.flush()
    return publication


def update_existing_publication(
    *,
    publication: Publication,
    candidate: PublicationCandidate,
) -> None:
    if candidate.cluster_id and publication.cluster_id is None:
        publication.cluster_id = candidate.cluster_id
    if not publication.title_raw:
        publication.title_raw = candidate.title
        publication.title_normalized = normalize_title(candidate.title)
    if candidate.year is not None:
        publication.year = candidate.year
    if candidate.citation_count is not None:
        publication.citation_count = int(candidate.citation_count)
    if candidate.authors_text:
        publication.author_text = candidate.authors_text
    if candidate.venue_text:
        publication.venue_text = candidate.venue_text
    if candidate.title_url:
        publication.pub_url = build_publication_url(candidate.title_url)


async def resolve_publication(
    db_session: AsyncSession,
    candidate: PublicationCandidate,
) -> Publication:
    validate_publication_candidate(candidate)
    fingerprint = build_publication_fingerprint(candidate)
    cluster_publication = await find_publication_by_cluster(
        db_session,
        cluster_id=candidate.cluster_id,
    )
    fingerprint_publication = await find_publication_by_fingerprint(
        db_session,
        fingerprint=fingerprint,
    )
    publication = select_existing_publication(
        cluster_publication=cluster_publication,
        fingerprint_publication=fingerprint_publication,
    )
    if publication is None:
        canonical_hash = compute_canonical_title_hash(candidate.title)
        publication = await find_publication_by_canonical_title_hash(
            db_session,
            canonical_title_hash=canonical_hash,
        )
    if publication is None:
        created = await create_publication(
            db_session,
            candidate=candidate,
            fingerprint=fingerprint,
        )
        await identifier_service.sync_identifiers_for_publication_fields(
            db_session,
            publication=created,
        )
        return created
    update_existing_publication(
        publication=publication,
        candidate=candidate,
    )
    await identifier_service.sync_identifiers_for_publication_fields(
        db_session,
        publication=publication,
    )
    return publication


async def upsert_profile_publications(
    db_session: AsyncSession,
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    publications: list[PublicationCandidate],
) -> int:
    seen_publication_ids: set[int] = set()
    discovered_count = 0

    for candidate in publications:
        publication = await resolve_publication(db_session, candidate)
        if publication.id in seen_publication_ids:
            continue
        seen_publication_ids.add(publication.id)

        link_result = await db_session.execute(
            select(ScholarPublication).where(
                ScholarPublication.scholar_profile_id == scholar.id,
                ScholarPublication.publication_id == publication.id,
            )
        )
        link = link_result.scalar_one_or_none()
        if link is not None:
            continue

        link = ScholarPublication(
            scholar_profile_id=scholar.id,
            publication_id=publication.id,
            is_read=False,
            first_seen_run_id=run.id,
        )
        db_session.add(link)
        discovered_count += 1

        await commit_discovered_publication(
            db_session,
            run=run,
            scholar=scholar,
            publication=publication,
        )

    if not scholar.baseline_completed:
        scholar.baseline_completed = True

    return discovered_count


async def commit_discovered_publication(
    db_session: AsyncSession,
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    publication: Publication,
) -> None:
    run.new_pub_count = int(run.new_pub_count or 0) + 1
    await db_session.commit()
    await run_events.publish(
        run_id=run.id,
        event_type="publication_discovered",
        data={
            "publication_id": publication.id,
            "title": publication.title_raw,
            "pub_url": publication.pub_url,
            "scholar_profile_id": scholar.id,
            "scholar_label": scholar.display_name or scholar.scholar_id,
            "first_seen_at": datetime.now(UTC).isoformat(),
            "new_publication_count": int(run.new_pub_count or 0),
        },
    )
