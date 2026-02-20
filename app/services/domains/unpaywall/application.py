from __future__ import annotations

import logging
import re
from urllib.parse import unquote

from app.services.domains.crossref.application import discover_doi_for_publication
from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem
from app.services.domains.doi.normalize import normalize_doi
from app.settings import settings

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
DOI_PREFIX_RE = re.compile(r"\bdoi\s*[:=]\s*(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
UNPAYWALL_URL_TEMPLATE = "https://api.unpaywall.org/v2/{doi}"
logger = logging.getLogger(__name__)


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


def _payload_pdf_url(payload: dict) -> str | None:
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        pdf_url = best.get("url_for_pdf")
        if isinstance(pdf_url, str) and pdf_url.strip():
            return pdf_url.strip()
    locations = payload.get("oa_locations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        if not isinstance(location, dict):
            continue
        pdf_url = location.get("url_for_pdf")
        if isinstance(pdf_url, str) and pdf_url.strip():
            return pdf_url.strip()
    return None


async def _fetch_unpaywall_payload_by_doi(
    *,
    client,
    doi: str,
    email: str,
) -> dict | None:
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
        if payload is not None and _payload_pdf_url(payload):
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


def _doi_and_pdf_from_payload(payload: dict) -> tuple[str | None, str | None]:
    doi = normalize_doi(str(payload.get("doi") or ""))
    return doi, _payload_pdf_url(payload)


def _resolution_targets(items: list[PublicationListItem]) -> list[PublicationListItem]:
    return [item for item in items if not item.pdf_url]


def _crossref_budget_value() -> int:
    return max(int(settings.crossref_max_lookups_per_request), 0)


async def resolve_publication_oa_metadata(
    items: list[PublicationListItem],
    *,
    request_email: str | None = None,
) -> dict[int, tuple[str | None, str | None]]:
    if not settings.unpaywall_enabled:
        return {}
    email = _email_for_request(request_email)
    if email is None:
        logger.debug("unpaywall.resolve_skipped_missing_email")
        return {}
    import httpx

    timeout_seconds = max(float(settings.unpaywall_timeout_seconds), 0.5)
    resolved: dict[int, tuple[str | None, str | None]] = {}
    crossref_budget = _crossref_budget_value()
    crossref_lookups = 0
    targets = _resolution_targets(items)[: max(int(settings.unpaywall_max_items_per_request), 0)]
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for item in targets:
            allow_crossref = crossref_budget > 0 and crossref_lookups < crossref_budget
            payload, used_crossref = await _resolve_item_payload(
                client=client,
                item=item,
                email=email,
                allow_crossref=allow_crossref,
            )
            if used_crossref:
                crossref_lookups += 1
            if not isinstance(payload, dict):
                continue
            resolved[item.publication_id] = _doi_and_pdf_from_payload(payload)
    resolved_count = sum(1 for _doi, pdf in resolved.values() if pdf)
    doi_input_count = len([item for item in items if _publication_doi(item)])
    target_doi_count = len([item for item in targets if _publication_doi(item)])
    _log_resolution_summary(
        publication_count=len(items),
        doi_input_count=doi_input_count,
        search_attempt_count=max(0, len(targets) - target_doi_count),
        resolved_pdf_count=resolved_count,
        email=email,
    )
    return resolved


async def resolve_publication_pdf_urls(
    items: list[PublicationListItem],
    *,
    request_email: str | None = None,
) -> dict[int, str | None]:
    resolved = await resolve_publication_oa_metadata(items, request_email=request_email)
    return {publication_id: pdf for publication_id, (_doi, pdf) in resolved.items()}
