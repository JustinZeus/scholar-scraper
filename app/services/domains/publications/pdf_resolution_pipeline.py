from __future__ import annotations

from dataclasses import dataclass
import logging
from urllib.parse import urlparse

import httpx

from app.services.domains.publications.types import PublicationListItem
from app.services.domains.scholar.publication_pdf import (
    ScholarPublicationLinkCandidate,
    ScholarPublicationLinkCandidates,
    fetch_link_candidates_from_scholar_publication_page,
)
from app.services.domains.unpaywall import pdf_discovery as pdf_discovery_service
from app.services.domains.unpaywall.application import OaResolutionOutcome, resolve_publication_oa_outcomes
from app.settings import settings

logger = logging.getLogger(__name__)

PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE = "scholar_publication_page"
PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE_UNLABELED = "scholar_publication_page_unlabeled_fallback"
PDF_PATH_TOKEN = "/pdf/"
HTTP_TIMEOUT_FLOOR_SECONDS = 0.5


@dataclass(frozen=True)
class PipelineOutcome:
    outcome: OaResolutionOutcome | None
    scholar_candidates: ScholarPublicationLinkCandidates | None


async def resolve_publication_pdf_outcome_for_row(
    *,
    row: PublicationListItem,
    request_email: str | None,
) -> PipelineOutcome:
    candidates = await _safe_scholar_candidates(row.pub_url)
    labeled = _labeled_candidate(candidates)
    if labeled is not None:
        return PipelineOutcome(_scholar_outcome(row=row, candidate=labeled), candidates)
    oa_outcome = await _oa_outcome(row=row, request_email=request_email)
    if _oa_has_pdf(oa_outcome):
        return PipelineOutcome(oa_outcome, candidates)
    unlabeled = _unlabeled_candidate(candidates)
    if unlabeled is None:
        return PipelineOutcome(oa_outcome, candidates)
    fallback_outcome = await _unlabeled_fallback_outcome(row=row, candidate=unlabeled)
    if fallback_outcome is not None:
        return PipelineOutcome(fallback_outcome, candidates)
    return PipelineOutcome(oa_outcome, candidates)


async def _safe_scholar_candidates(pub_url: str | None) -> ScholarPublicationLinkCandidates | None:
    try:
        return await fetch_link_candidates_from_scholar_publication_page(pub_url)
    except Exception as exc:  # pragma: no cover - defensive boundary
        logger.warning(
            "publications.pdf_resolution.scholar_candidates_failed",
            extra={"event": "publications.pdf_resolution.scholar_candidates_failed", "error": str(exc)},
        )
        return None


def _labeled_candidate(
    candidates: ScholarPublicationLinkCandidates | None,
) -> ScholarPublicationLinkCandidate | None:
    if candidates is None:
        return None
    return candidates.labeled_candidate


def _unlabeled_candidate(
    candidates: ScholarPublicationLinkCandidates | None,
) -> ScholarPublicationLinkCandidate | None:
    if candidates is None:
        return None
    return candidates.fallback_candidate


def _scholar_outcome(
    *,
    row: PublicationListItem,
    candidate: ScholarPublicationLinkCandidate,
) -> OaResolutionOutcome:
    source = (
        PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE
        if candidate.label_present
        else PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE_UNLABELED
    )
    return OaResolutionOutcome(
        publication_id=row.publication_id,
        doi=row.doi,
        pdf_url=candidate.url,
        failure_reason=None,
        source=source,
        used_crossref=False,
    )


async def _oa_outcome(
    *,
    row: PublicationListItem,
    request_email: str | None,
) -> OaResolutionOutcome | None:
    outcomes = await resolve_publication_oa_outcomes([row], request_email=request_email)
    return outcomes.get(row.publication_id)


def _oa_has_pdf(outcome: OaResolutionOutcome | None) -> bool:
    return bool(outcome and outcome.pdf_url)


async def _unlabeled_fallback_outcome(
    *,
    row: PublicationListItem,
    candidate: ScholarPublicationLinkCandidate,
) -> OaResolutionOutcome | None:
    pdf_url = await _validated_pdf_url(candidate.url)
    if pdf_url is None:
        return None
    return _scholar_outcome(row=row, candidate=ScholarPublicationLinkCandidate(
        url=pdf_url,
        confidence_score=candidate.confidence_score,
        label_present=False,
        reason=candidate.reason,
    ))


async def _validated_pdf_url(candidate_url: str) -> str | None:
    if _looks_direct_pdf(candidate_url):
        return candidate_url
    timeout_seconds = _discovery_timeout_seconds()
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        if await pdf_discovery_service._candidate_is_pdf(client, candidate_url=candidate_url):
            return candidate_url
        return await pdf_discovery_service.resolve_pdf_from_landing_page(client, page_url=candidate_url)


def _looks_direct_pdf(url: str | None) -> bool:
    if pdf_discovery_service.looks_like_pdf_url(url):
        return True
    if not isinstance(url, str):
        return False
    path = (urlparse(url).path or "").lower()
    return PDF_PATH_TOKEN in path


def _discovery_timeout_seconds() -> float:
    return max(float(settings.unpaywall_timeout_seconds), HTTP_TIMEOUT_FLOOR_SECONDS)
