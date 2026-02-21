from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

from app.services.domains.unpaywall.rate_limit import wait_for_unpaywall_slot
from app.settings import settings

PDF_MIME = "application/pdf"
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


class _LandingPdfParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base_href: str | None = None
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): (value or "").strip() for key, value in attrs}
        if tag == "base":
            self.base_href = attrs_map.get("href") or self.base_href
            return
        if tag == "meta":
            self._append_meta_candidate(attrs_map)
            return
        if tag == "link":
            self._append_link_candidate(attrs_map)
            return
        if tag == "a":
            self._append_anchor_candidate(attrs_map)

    def _append_meta_candidate(self, attrs_map: dict[str, str]) -> None:
        meta_name = (attrs_map.get("name") or attrs_map.get("property") or "").lower()
        if meta_name != "citation_pdf_url":
            return
        content = attrs_map.get("content")
        if content:
            self.candidates.append(content)

    def _append_link_candidate(self, attrs_map: dict[str, str]) -> None:
        href = attrs_map.get("href")
        link_type = (attrs_map.get("type") or "").lower()
        if href and "pdf" in link_type:
            self.candidates.append(href)

    def _append_anchor_candidate(self, attrs_map: dict[str, str]) -> None:
        href = attrs_map.get("href")
        if href:
            self.candidates.append(href)


def looks_like_pdf_url(url: str | None) -> bool:
    if not isinstance(url, str):
        return False
    value = url.strip()
    if not value:
        return False
    parsed = urlparse(value)
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    return path.endswith(".pdf") or ".pdf" in query


def _normalized_candidate_urls(*, page_url: str, html: str) -> list[str]:
    parser = _LandingPdfParser()
    parser.feed(html)
    parser.close()
    base_url = urljoin(page_url, parser.base_href) if parser.base_href else page_url
    raw_candidates = [*parser.candidates, *_text_url_candidates(html)]
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        absolute = urljoin(base_url, raw.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        deduped.append(absolute)
    return sorted(deduped, key=_candidate_sort_key)


def _text_url_candidates(html: str) -> list[str]:
    candidates: list[str] = []
    for match in URL_RE.findall(html):
        cleaned = match.rstrip(".,);]}>")
        if "pdf" not in cleaned.lower():
            continue
        candidates.append(cleaned)
    return candidates


def _candidate_sort_key(candidate: str) -> tuple[int, str]:
    lowered = candidate.lower()
    if looks_like_pdf_url(candidate):
        return (0, lowered)
    if any(token in lowered for token in ("doi", "full", "article", "download")):
        return (1, lowered)
    return (2, lowered)


def _is_html_response(response) -> bool:
    content_type = str(response.headers.get("content-type") or "").lower()
    return "text/html" in content_type or "application/xhtml+xml" in content_type


async def _fetch_page_html(client, *, page_url: str) -> str | None:
    await wait_for_unpaywall_slot(min_interval_seconds=settings.unpaywall_min_interval_seconds)
    response = await client.get(page_url, follow_redirects=True)
    if response.status_code != 200 or not _is_html_response(response):
        return None
    text = response.text or ""
    return text[: max(int(settings.unpaywall_pdf_discovery_max_html_bytes), 0)]


async def _candidate_is_pdf(client, *, candidate_url: str) -> bool:
    if looks_like_pdf_url(candidate_url):
        return True
    await wait_for_unpaywall_slot(min_interval_seconds=settings.unpaywall_min_interval_seconds)
    response = await client.get(candidate_url, follow_redirects=True)
    content_type = str(response.headers.get("content-type") or "").lower()
    return response.status_code == 200 and PDF_MIME in content_type


def _candidate_limit() -> int:
    return max(int(settings.unpaywall_pdf_discovery_max_candidates), 1)


async def _resolve_pdf_from_candidate_page(client, *, candidate_url: str) -> str | None:
    html = await _fetch_page_html(client, page_url=candidate_url)
    if not html:
        return None
    nested_candidates = _normalized_candidate_urls(page_url=candidate_url, html=html)
    for nested in nested_candidates[: _candidate_limit()]:
        if await _candidate_is_pdf(client, candidate_url=nested):
            return nested
    return None


async def resolve_pdf_from_landing_page(client, *, page_url: str) -> str | None:
    if not settings.unpaywall_pdf_discovery_enabled:
        return None
    html = await _fetch_page_html(client, page_url=page_url)
    if not html:
        return None
    candidates = _normalized_candidate_urls(page_url=page_url, html=html)
    for candidate in candidates[: _candidate_limit()]:
        if await _candidate_is_pdf(client, candidate_url=candidate):
            return candidate
        nested_pdf = await _resolve_pdf_from_candidate_page(client, candidate_url=candidate)
        if nested_pdf:
            return nested_pdf
    return None
