from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import unquote

from app.services.domains.crossref.application import discover_doi_for_publication
from app.services.domains.doi.normalize import normalize_doi
from app.services.domains.unpaywall.pdf_discovery import (
    looks_like_pdf_url,
    resolve_pdf_from_landing_page,
)
from app.services.domains.unpaywall.rate_limit import wait_for_unpaywall_slot
from app.settings import settings

if TYPE_CHECKING:
    from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
DOI_PREFIX_RE = re.compile(r"\bdoi\s*[:=]\s*(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
UNPAYWALL_URL_TEMPLATE = "https://api.unpaywall.org/v2/{doi}"
FAILURE_MISSING_DOI = "missing_doi"
FAILURE_NO_RECORD = "no_unpaywall_record"
FAILURE_NO_PDF = "no_pdf_found"
FAILURE_RESOLUTION_EXCEPTION = "resolution_exception"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OaResolutionOutcome:
    publication_id: int
    doi: str | None
    pdf_url: str | None
    failure_reason: str | None
    source: str | None
    used_crossref: bool


def _extract_doi_candidate(text: str | None) -> str | None:
    if not text:
        return None
    decoded = unquote(text)
    match = DOI_PATTERN.search(decoded)
    if not match:
        return None
    return match.group(0).rstrip(" .;,)")


def _extract_explicit_doi(text: str | None) -> str | None:
    if not text:
        return None
    decoded = unquote(text)
    url_match = DOI_URL_RE.search(decoded)
    if url_match:
        return normalize_doi(url_match.group(1))
    prefix_match = DOI_PREFIX_RE.search(decoded)
    if prefix_match:
        return normalize_doi(prefix_match.group(1))
    return None


def _publication_doi(item: PublicationListItem | UnreadPublicationItem) -> str | None:
    stored = normalize_doi(item.doi)
    if stored:
        in_metadata = any(
            normalize_doi(_extract_explicit_doi(value)) == stored
            for value in (item.pub_url, item.venue_text)
        )
        if in_metadata:
            return stored
    pub_url_doi = _extract_doi_candidate(item.pub_url)
    if pub_url_doi:
        return normalize_doi(pub_url_doi)
    return (
        _extract_explicit_doi(item.pub_url)
        or _extract_explicit_doi(item.venue_text)
    )


def _payload_locations(payload: dict) -> list[dict]:
    locations: list[dict] = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    oa_locations = payload.get("oa_locations")
    if isinstance(oa_locations, list):
        locations.extend(location for location in oa_locations if isinstance(location, dict))
    return locations


def _location_value(location: dict, key: str) -> str | None:
    value = location.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _payload_pdf_candidates(payload: dict) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for location in _payload_locations(payload):
        candidate = _location_value(location, "url_for_pdf")
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _payload_landing_candidates(payload: dict) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for location in _payload_locations(payload):
        candidate = _location_value(location, "url")
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _crawl_targets(
    *,
    payload: dict,
    pdf_candidates: list[str],
) -> list[str]:
    targets = _payload_landing_candidates(payload)
    seen = set(targets)
    for candidate in pdf_candidates:
        if candidate in seen:
            continue
        targets.append(candidate)
        seen.add(candidate)
    doi = normalize_doi(str(payload.get("doi") or ""))
    doi_landing_url = f"https://doi.org/{doi}" if doi else None
    if doi_landing_url and doi_landing_url not in seen:
        targets.append(doi_landing_url)
    return targets


def _has_direct_payload_pdf(payload: dict) -> bool:
    return any(looks_like_pdf_url(candidate) for candidate in _payload_pdf_candidates(payload))


async def _resolved_pdf_url_from_payload(
    payload: dict,
    *,
    client,
) -> str | None:
    pdf_candidates = _payload_pdf_candidates(payload)
    for candidate in pdf_candidates:
        if looks_like_pdf_url(candidate):
            return candidate
    for page_url in _crawl_targets(payload=payload, pdf_candidates=pdf_candidates)[:3]:
        discovered = await resolve_pdf_from_landing_page(client, page_url=page_url)
        if discovered:
            logger.info(
                "unpaywall.pdf_discovered_from_landing",
                extra={"event": "unpaywall.pdf_discovered_from_landing", "landing_url": page_url},
            )
            return discovered
    return None


async def _fetch_unpaywall_payload_by_doi(
    *,
    client,
    doi: str,
    email: str,
) -> dict | None:
    await wait_for_unpaywall_slot(min_interval_seconds=settings.unpaywall_min_interval_seconds)
    response = await client.get(
        UNPAYWALL_URL_TEMPLATE.format(doi=doi),
        params={"email": email},
    )
    if response.status_code != 200:
        return None
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    return payload


def _email_for_request(request_email: str | None) -> str | None:
    email = (request_email or "").strip() or settings.unpaywall_email.strip()
    return email or None


def _log_resolution_summary(
    *,
    publication_count: int,
    doi_input_count: int,
    search_attempt_count: int,
    resolved_pdf_count: int,
    email: str,
) -> None:
    logger.info(
        "unpaywall.resolve_completed",
        extra={
            "event": "unpaywall.resolve_completed",
            "publication_count": publication_count,
            "doi_input_count": doi_input_count,
            "search_attempt_count": search_attempt_count,
            "resolved_pdf_count": resolved_pdf_count,
            "email_domain": email.split("@", 1)[-1] if "@" in email else None,
        },
    )


async def _resolve_item_payload(
    *,
    client,
    item: PublicationListItem,
    email: str,
    allow_crossref: bool,
) -> tuple[dict | None, bool]:
    doi = _publication_doi(item)
    payload: dict | None = None
    if doi:
        payload = await _fetch_unpaywall_payload_by_doi(client=client, doi=doi, email=email)
        if payload is not None and _has_direct_payload_pdf(payload):
            return payload, False
    if not allow_crossref or not settings.crossref_enabled:
        return payload, False
    crossref_doi = await discover_doi_for_publication(
        item=item,
        max_rows=settings.crossref_max_rows,
        email=email,
    )
    if crossref_doi is None or crossref_doi == doi:
        return payload, crossref_doi is not None
    crossref_payload = await _fetch_unpaywall_payload_by_doi(
        client=client,
        doi=crossref_doi,
        email=email,
    )
    if crossref_payload is not None:
        return crossref_payload, True
    return payload, True


async def _doi_and_pdf_from_payload(
    payload: dict,
    *,
    client,
) -> tuple[str | None, str | None]:
    doi = normalize_doi(str(payload.get("doi") or ""))
    return doi, await _resolved_pdf_url_from_payload(payload, client=client)


def _resolution_targets(items: list[PublicationListItem]) -> list[PublicationListItem]:
    return [item for item in items if not item.pdf_url]


def _crossref_budget_value() -> int:
    return max(int(settings.crossref_max_lookups_per_request), 0)


def _outcome_with_failure(
    *,
    item: PublicationListItem,
    failure_reason: str,
    used_crossref: bool,
) -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=item.publication_id,
        doi=_publication_doi(item),
        pdf_url=None,
        failure_reason=failure_reason,
        source=None,
        used_crossref=used_crossref,
    )


def _missing_payload_failure_reason(item: PublicationListItem, *, used_crossref: bool) -> str:
    if _publication_doi(item):
        return FAILURE_NO_RECORD
    if used_crossref:
        return FAILURE_NO_RECORD
    return FAILURE_MISSING_DOI


def _source_name(*, used_crossref: bool) -> str:
    return "crossref+unpaywall" if used_crossref else "unpaywall"


def _outcome_from_payload(
    *,
    item: PublicationListItem,
    doi: str | None,
    pdf_url: str | None,
    used_crossref: bool,
) -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=item.publication_id,
        doi=doi,
        pdf_url=pdf_url,
        failure_reason=None if pdf_url else FAILURE_NO_PDF,
        source=_source_name(used_crossref=used_crossref),
        used_crossref=used_crossref,
    )


def _resolved_pdf_count(outcomes: dict[int, OaResolutionOutcome]) -> int:
    return sum(1 for outcome in outcomes.values() if outcome.pdf_url)


def _outcome_metadata(outcomes: dict[int, OaResolutionOutcome]) -> dict[int, tuple[str | None, str | None]]:
    return {
        publication_id: (outcome.doi, outcome.pdf_url)
        for publication_id, outcome in outcomes.items()
    }


async def _resolve_outcome_for_item(
    *,
    client,
    item: PublicationListItem,
    email: str,
    allow_crossref: bool,
) -> OaResolutionOutcome:
    payload, used_crossref = await _resolve_item_payload(
        client=client,
        item=item,
        email=email,
        allow_crossref=allow_crossref,
    )
    if not isinstance(payload, dict):
        return _outcome_with_failure(
            item=item,
            failure_reason=_missing_payload_failure_reason(item, used_crossref=used_crossref),
            used_crossref=used_crossref,
        )
    doi, pdf_url = await _doi_and_pdf_from_payload(payload, client=client)
    return _outcome_from_payload(
        item=item,
        doi=doi,
        pdf_url=pdf_url,
        used_crossref=used_crossref,
    )


def _doi_input_count(items: list[PublicationListItem]) -> int:
    return len([item for item in items if _publication_doi(item)])


def _search_attempt_count(*, targets: list[PublicationListItem]) -> int:
    return len([item for item in targets if not _publication_doi(item)])


async def _safe_outcome_for_item(
    *,
    client,
    item: PublicationListItem,
    email: str,
    allow_crossref: bool,
) -> OaResolutionOutcome:
    try:
        return await _resolve_outcome_for_item(
            client=client,
            item=item,
            email=email,
            allow_crossref=allow_crossref,
        )
    except Exception as exc:  # pragma: no cover - defensive network boundary
        logger.warning(
            "unpaywall.resolve_item_failed",
            extra={
                "event": "unpaywall.resolve_item_failed",
                "publication_id": item.publication_id,
                "error": str(exc),
            },
        )
        return _outcome_with_failure(
            item=item,
            failure_reason=FAILURE_RESOLUTION_EXCEPTION,
            used_crossref=allow_crossref and settings.crossref_enabled,
        )


async def _resolve_outcomes_with_client(
    *,
    client,
    targets: list[PublicationListItem],
    email: str,
) -> dict[int, OaResolutionOutcome]:
    outcomes: dict[int, OaResolutionOutcome] = {}
    crossref_budget = _crossref_budget_value()
    crossref_lookups = 0
    for item in targets:
        allow_crossref = crossref_budget > 0 and crossref_lookups < crossref_budget
        outcome = await _safe_outcome_for_item(
            client=client,
            item=item,
            email=email,
            allow_crossref=allow_crossref,
        )
        if outcome.used_crossref:
            crossref_lookups += 1
        outcomes[item.publication_id] = outcome
    return outcomes


async def resolve_publication_oa_metadata(
    items: list[PublicationListItem],
    *,
    request_email: str | None = None,
) -> dict[int, tuple[str | None, str | None]]:
    outcomes = await resolve_publication_oa_outcomes(items, request_email=request_email)
    return _outcome_metadata(outcomes)


async def resolve_publication_oa_outcomes(
    items: list[PublicationListItem],
    *,
    request_email: str | None = None,
) -> dict[int, OaResolutionOutcome]:
    if not settings.unpaywall_enabled:
        return {}
    email = _email_for_request(request_email)
    if email is None:
        logger.debug("unpaywall.resolve_skipped_missing_email")
        return {}
    import httpx

    timeout_seconds = max(float(settings.unpaywall_timeout_seconds), 0.5)
    targets = _resolution_targets(items)[: max(int(settings.unpaywall_max_items_per_request), 0)]
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        outcomes = await _resolve_outcomes_with_client(
            client=client,
            targets=targets,
            email=email,
        )
    _log_resolution_summary(
        publication_count=len(items),
        doi_input_count=_doi_input_count(items),
        search_attempt_count=_search_attempt_count(targets=targets),
        resolved_pdf_count=_resolved_pdf_count(outcomes),
        email=email,
    )
    return outcomes


async def resolve_publication_pdf_urls(
    items: list[PublicationListItem],
    *,
    request_email: str | None = None,
) -> dict[int, str | None]:
    resolved = await resolve_publication_oa_metadata(items, request_email=request_email)
    return {publication_id: pdf for publication_id, (_doi, pdf) in resolved.items()}
