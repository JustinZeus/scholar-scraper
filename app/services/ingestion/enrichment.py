from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    Publication,
    RunStatus,
    ScholarProfile,
    ScholarPublication,
)
from app.logging_utils import structured_log
from app.services.arxiv.errors import ArxivRateLimitError
from app.services.publication_identifiers import application as identifier_service
from app.services.runs.events import run_events
from app.services.scholar.parser import PublicationCandidate
from app.settings import settings

logger = logging.getLogger(__name__)


def _sanitize_titles(publications: list) -> list[str]:
    titles = []
    for p in publications:
        raw = getattr(p, "title_raw", None) or getattr(p, "title", None)
        if not raw or not raw.strip():
            continue
        safe = " ".join(re.sub(r"[^\w\s]", " ", raw).split())
        if safe:
            titles.append(safe)
    return titles


# OpenAlex (and most HTTP servers) struggle with very long query strings.
# Non-ASCII characters expand significantly when percent-encoded in URLs,
# so a fixed batch count is unreliable.  Instead we cap the combined
# byte-length of the pipe-joined title filter value to stay well within
# safe URL limits (~4 KiB of filter text ≈ ~6 KiB when percent-encoded).
_MAX_TITLE_FILTER_BYTES = 4_000


def _chunk_titles_by_url_length(
    titles: list[str],
    max_bytes: int = _MAX_TITLE_FILTER_BYTES,
) -> list[list[str]]:
    """Split *titles* into chunks whose pipe-joined UTF-8 size stays under *max_bytes*."""
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_bytes = 0

    for title in titles:
        title_bytes = len(title.encode("utf-8"))
        # Account for the pipe separator between titles
        separator = 3 if current_chunk else 0  # len("|".encode) but url-encoded as %7C = 3
        if current_chunk and current_bytes + separator + title_bytes > max_bytes:
            chunks.append(current_chunk)
            current_chunk = [title]
            current_bytes = title_bytes
        else:
            current_chunk.append(title)
            current_bytes += separator + title_bytes

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


class EnrichmentRunner:
    """Post-run OpenAlex enrichment logic.

    Receives service dependencies at construction so it can be tested
    independently of ``ScholarIngestionService``.
    """

    async def run_is_canceled(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
    ) -> bool:
        check_result = await db_session.execute(select(CrawlRun.status).where(CrawlRun.id == run_id))
        status = check_result.scalar_one_or_none()
        if status is None:
            raise RuntimeError(f"Missing crawl_run for run_id={run_id}.")
        return status == RunStatus.CANCELED

    async def _load_unenriched_publications(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
    ) -> tuple[int, list[Publication]]:
        run_result = await db_session.execute(select(CrawlRun.user_id).where(CrawlRun.id == run_id))
        user_id = run_result.scalar_one()
        cooldown_threshold = datetime.now(UTC) - timedelta(days=7)
        stmt = (
            select(Publication)
            .join(ScholarPublication)
            .join(ScholarProfile, ScholarPublication.scholar_profile_id == ScholarProfile.id)
            .where(
                ScholarProfile.user_id == user_id,
                Publication.openalex_enriched.is_(False),
                or_(
                    Publication.openalex_last_attempt_at.is_(None),
                    Publication.openalex_last_attempt_at < cooldown_threshold,
                ),
            )
            .distinct()
        )
        result = await db_session.execute(stmt)
        return user_id, list(result.scalars().all())

    async def _enrich_batch(
        self,
        db_session: AsyncSession,
        *,
        batch: list[Publication],
        run_id: int,
        openalex_works: list,
        now: datetime,
        arxiv_lookup_allowed: bool,
    ) -> tuple[bool, bool]:
        from app.services.openalex.matching import find_best_match

        for p in batch:
            if await self.run_is_canceled(db_session, run_id=run_id):
                structured_log(logger, "info", "ingestion.enrichment_aborted", run_id=run_id)
                return False, arxiv_lookup_allowed
            p.openalex_last_attempt_at = now
            arxiv_lookup_allowed = await self._discover_identifiers_for_enrichment(
                db_session,
                publication=p,
                run_id=run_id,
                allow_arxiv_lookup=arxiv_lookup_allowed,
            )
            match = find_best_match(
                target_title=p.title_raw,
                target_year=p.year,
                target_authors=p.author_text or "",
                candidates=openalex_works,
            )
            if match:
                p.year = match.publication_year if match.publication_year is not None else p.year
                p.citation_count = match.cited_by_count if match.cited_by_count is not None else p.citation_count
                p.pdf_url = match.oa_url if match.oa_url is not None else p.pdf_url
                p.openalex_enriched = True
        return True, arxiv_lookup_allowed

    async def _flush_and_sweep_duplicates(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
    ) -> None:
        await db_session.flush()
        from app.services.publications.dedup import sweep_identifier_duplicates

        merge_count = await sweep_identifier_duplicates(db_session)
        if merge_count:
            structured_log(
                logger,
                "info",
                "ingestion.identifier_dedup_sweep",
                merged_count=merge_count,
                run_id=run_id,
            )

    async def enrich_pending_publications(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
        openalex_api_key: str | None = None,
    ) -> None:
        from app.services.openalex.client import (
            OpenAlexBudgetExhaustedError,
            OpenAlexClient,
            OpenAlexRateLimitError,
        )

        _, publications = await self._load_unenriched_publications(db_session, run_id=run_id)
        if not publications:
            return

        resolved_key = openalex_api_key or settings.openalex_api_key
        client = OpenAlexClient(api_key=resolved_key, mailto=settings.crossref_api_mailto)
        now = datetime.now(UTC)
        arxiv_lookup_allowed = True

        all_titles = _sanitize_titles(publications)
        title_chunks = _chunk_titles_by_url_length(all_titles)

        # Build a mapping from sanitized title → publications for batch association
        title_to_pubs: dict[str, list[Publication]] = {}
        for p in publications:
            raw = getattr(p, "title_raw", None) or getattr(p, "title", None)
            if not raw or not raw.strip():
                continue
            safe = " ".join(re.sub(r"[^\w\s]", " ", raw).split())
            if safe:
                title_to_pubs.setdefault(safe, []).append(p)

        for title_chunk in title_chunks:
            if await self.run_is_canceled(db_session, run_id=run_id):
                structured_log(logger, "info", "ingestion.enrichment_aborted", run_id=run_id)
                return
            batch = []
            for t in title_chunk:
                batch.extend(title_to_pubs.get(t, []))
            if not batch:
                continue
            try:
                openalex_works = await client.get_works_by_filter(
                    {"title.search": "|".join(title_chunk)}, limit=len(title_chunk) * 3
                )
            except OpenAlexBudgetExhaustedError:
                structured_log(logger, "warning", "ingestion.openalex_budget_exhausted", run_id=run_id)
                break
            except OpenAlexRateLimitError:
                structured_log(logger, "warning", "ingestion.openalex_rate_limited", run_id=run_id)
                await asyncio.sleep(60)
                continue
            except Exception as e:
                structured_log(logger, "warning", "ingestion.openalex_enrichment_failed", error=str(e), run_id=run_id)
                for p in batch:
                    p.openalex_last_attempt_at = now
                continue
            should_continue, arxiv_lookup_allowed = await self._enrich_batch(
                db_session,
                batch=batch,
                run_id=run_id,
                openalex_works=openalex_works,
                now=now,
                arxiv_lookup_allowed=arxiv_lookup_allowed,
            )
            if not should_continue:
                return

        await self._flush_and_sweep_duplicates(db_session, run_id=run_id)

    async def _discover_identifiers_for_enrichment(
        self,
        db_session: AsyncSession,
        *,
        publication: Publication,
        run_id: int,
        allow_arxiv_lookup: bool,
    ) -> bool:
        if not allow_arxiv_lookup:
            await identifier_service.sync_identifiers_for_publication_fields(
                db_session,
                publication=publication,
            )
            await self._publish_identifier_update_event(
                db_session,
                run_id=run_id,
                publication_id=int(publication.id),
            )
            return False
        try:
            await identifier_service.discover_and_sync_identifiers_for_publication(
                db_session,
                publication=publication,
                scholar_label=publication.author_text or "",
            )
            await self._publish_identifier_update_event(
                db_session,
                run_id=run_id,
                publication_id=int(publication.id),
            )
            return True
        except ArxivRateLimitError:
            structured_log(
                logger,
                "warning",
                "ingestion.arxiv_rate_limited",
                run_id=run_id,
                publication_id=int(publication.id),
                detail="arXiv temporarily disabled for remaining enrichment pass",
            )
            await identifier_service.sync_identifiers_for_publication_fields(
                db_session,
                publication=publication,
            )
            await self._publish_identifier_update_event(
                db_session,
                run_id=run_id,
                publication_id=int(publication.id),
            )
            return False

    async def _publish_identifier_update_event(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
        publication_id: int,
    ) -> None:
        display = await identifier_service.display_identifier_for_publication_id(
            db_session,
            publication_id=publication_id,
        )
        if display is None:
            return
        await run_events.publish(
            run_id=run_id,
            event_type="identifier_updated",
            data={
                "publication_id": int(publication_id),
                "display_identifier": {
                    "kind": display.kind,
                    "value": display.value,
                    "label": display.label,
                    "url": display.url,
                    "confidence_score": float(display.confidence_score),
                },
            },
        )

    async def enrich_publications_with_openalex(
        self,
        scholar: ScholarProfile,
        publications: list[PublicationCandidate],
    ) -> list[PublicationCandidate]:
        if not publications:
            return publications

        from app.services.openalex.client import OpenAlexClient
        from app.services.openalex.matching import find_best_match

        client = OpenAlexClient(api_key=settings.openalex_api_key, mailto=settings.crossref_api_mailto)

        all_titles = _sanitize_titles(publications)
        title_chunks = _chunk_titles_by_url_length(all_titles)

        # Build title → publication mapping for batch association
        title_to_pubs: dict[str, list[PublicationCandidate]] = {}
        for p in publications:
            raw = getattr(p, "title", None)
            if not raw or not raw.strip():
                continue
            safe = " ".join(re.sub(r"[^\w\s]", " ", raw).split())
            if safe:
                title_to_pubs.setdefault(safe, []).append(p)

        # Collect publications that had no sanitizable title — pass through as-is
        pubs_with_titles = set()
        for titles in title_to_pubs.values():
            for p in titles:
                pubs_with_titles.add(id(p))

        enriched: list[PublicationCandidate] = []

        for title_chunk in title_chunks:
            batch = []
            for t in title_chunk:
                batch.extend(title_to_pubs.get(t, []))
            if not batch:
                continue

            try:
                openalex_works = await client.get_works_by_filter(
                    {"title.search": "|".join(title_chunk)}, limit=len(title_chunk) * 3
                )
            except Exception as e:
                structured_log(
                    logger,
                    "warning",
                    "ingestion.openalex_enrichment_failed",
                    error=str(e),
                    batch_size=len(batch),
                    scholar_id=scholar.id,
                )
                openalex_works = []

            for p in batch:
                match = find_best_match(
                    target_title=p.title,
                    target_year=p.year,
                    target_authors=p.authors_text or (scholar.display_name or scholar.scholar_id),
                    candidates=openalex_works,
                )
                if match:
                    new_p = PublicationCandidate(
                        title=p.title,
                        title_url=p.title_url,
                        cluster_id=p.cluster_id,
                        year=match.publication_year if match.publication_year is not None else p.year,
                        citation_count=match.cited_by_count if match.cited_by_count is not None else p.citation_count,
                        authors_text=p.authors_text,
                        venue_text=p.venue_text,
                        pdf_url=match.oa_url if match.oa_url is not None else p.pdf_url,
                    )
                    enriched.append(new_p)
                else:
                    enriched.append(p)

        # Append publications that had no sanitizable title (pass-through)
        for p in publications:
            if id(p) not in pubs_with_titles:
                enriched.append(p)

        return enriched
