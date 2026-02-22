from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from app.services.domains.scholar.parser_types import ScholarDomInvariantError
from app.services.domains.scholar.parser_utils import attr_href, normalize_space
from app.services.domains.scholar.rate_limit import wait_for_scholar_slot
from app.services.domains.scholar.source import LiveScholarSource
from app.services.domains.settings.application import resolve_request_delay_minimum
from app.settings import settings

CONTAINER_ID = "gsc_oci_title_gg"
PDF_LABEL_TOKEN = "[pdf]"
SCHOLAR_PDF_LABELED_CONFIDENCE = 0.98
SCHOLAR_PDF_UNLABELED_CONFIDENCE = 0.2
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class ScholarPublicationLinkCandidate:
    url: str
    confidence_score: float
    label_present: bool
    reason: str


@dataclass(frozen=True)
class ScholarPublicationLinkCandidates:
    container_seen: bool
    labeled_candidate: ScholarPublicationLinkCandidate | None
    fallback_candidate: ScholarPublicationLinkCandidate | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ParsedAnchor:
    href: str | None
    text: str


class _ScholarPublicationPdfParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.container_seen = False
        self.anchors: list[_ParsedAnchor] = []
        self._container_depth = 0
        self._anchor_depth = 0
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._increment_depths()
        if self._starts_container(tag, attrs):
            self.container_seen = True
            self._container_depth = 1
            return
        if self._container_depth <= 0 or tag != "a":
            return
        if self._anchor_depth > 0:
            return
        self._anchor_href = attr_href(attrs)
        self._anchor_parts = []
        self._anchor_depth = 1

    def handle_data(self, data: str) -> None:
        if self._anchor_depth > 0:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._anchor_depth > 0:
            self._anchor_depth -= 1
            if self._anchor_depth == 0:
                self._finish_anchor()
        if self._container_depth > 0:
            self._container_depth -= 1

    def _increment_depths(self) -> None:
        if self._container_depth > 0:
            self._container_depth += 1
        if self._anchor_depth > 0:
            self._anchor_depth += 1

    def _starts_container(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag != "div":
            return False
        attrs_map = {name.lower(): (value or "") for name, value in attrs}
        return attrs_map.get("id") == CONTAINER_ID

    def _finish_anchor(self) -> None:
        self.anchors.append(
            _ParsedAnchor(
                href=self._anchor_href,
                text=normalize_space("".join(self._anchor_parts)),
            )
        )
        self._anchor_href = None
        self._anchor_parts = []


def is_scholar_publication_detail_url(url: str | None) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        return False
    if parsed.netloc.lower() != "scholar.google.com":
        return False
    query = parse_qs(parsed.query)
    return _has_view_citation_params(query)


def _has_view_citation_params(query: dict[str, list[str]]) -> bool:
    view_op = (query.get("view_op") or [""])[0]
    citation = (query.get("citation_for_view") or [""])[0].strip()
    return view_op == "view_citation" and bool(citation)


def extract_link_candidates_from_publication_detail_html(html: str) -> ScholarPublicationLinkCandidates:
    parser = _parsed_publication_detail(html)
    if not parser.container_seen:
        return ScholarPublicationLinkCandidates(False, None, None)
    anchors = _validated_container_anchors(parser.anchors)
    labeled = _select_labeled_candidate(anchors)
    fallback = _select_fallback_candidate(anchors, labeled=labeled)
    warnings = _candidate_warnings(labeled=labeled, fallback=fallback)
    return ScholarPublicationLinkCandidates(True, labeled, fallback, warnings)


def _parsed_publication_detail(html: str) -> _ScholarPublicationPdfParser:
    parser = _ScholarPublicationPdfParser()
    parser.feed(html)
    parser.close()
    return parser


def _validated_container_anchors(anchors: list[_ParsedAnchor]) -> list[_ParsedAnchor]:
    if not anchors:
        raise ScholarDomInvariantError(
            code="layout_publication_link_container_missing_anchor",
            message="Scholar publication link container was present without an anchor.",
        )
    validated: list[_ParsedAnchor] = []
    for anchor in anchors:
        validated.append(_validated_anchor(anchor))
    return validated


def _validated_anchor(anchor: _ParsedAnchor) -> _ParsedAnchor:
    href = (anchor.href or "").strip()
    if not href:
        raise ScholarDomInvariantError(
            code="layout_publication_link_missing_href",
            message="Scholar publication link container anchor was missing href.",
        )
    parsed = urlparse(href)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ScholarDomInvariantError(
            code="layout_publication_link_invalid_scheme",
            message="Scholar publication link used a non-http URL.",
        )
    return _ParsedAnchor(href=href, text=anchor.text)


def _select_labeled_candidate(anchors: list[_ParsedAnchor]) -> ScholarPublicationLinkCandidate | None:
    for anchor in anchors:
        if PDF_LABEL_TOKEN in anchor.text.lower():
            return ScholarPublicationLinkCandidate(
                url=str(anchor.href),
                confidence_score=SCHOLAR_PDF_LABELED_CONFIDENCE,
                label_present=True,
                reason="scholar_link_labeled_pdf",
            )
    return None


def _select_fallback_candidate(
    anchors: list[_ParsedAnchor],
    *,
    labeled: ScholarPublicationLinkCandidate | None,
) -> ScholarPublicationLinkCandidate | None:
    for anchor in anchors:
        if labeled and anchor.href == labeled.url:
            continue
        return ScholarPublicationLinkCandidate(
            url=str(anchor.href),
            confidence_score=SCHOLAR_PDF_UNLABELED_CONFIDENCE,
            label_present=False,
            reason="scholar_link_unlabeled_fallback",
        )
    if labeled is None and anchors:
        anchor = anchors[0]
        return ScholarPublicationLinkCandidate(
            url=str(anchor.href),
            confidence_score=SCHOLAR_PDF_UNLABELED_CONFIDENCE,
            label_present=False,
            reason="scholar_link_unlabeled_fallback",
        )
    return None


def _candidate_warnings(
    *,
    labeled: ScholarPublicationLinkCandidate | None,
    fallback: ScholarPublicationLinkCandidate | None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if labeled is None and fallback is not None:
        warnings.append("scholar_publication_link_unlabeled_only")
    return tuple(warnings)


def _scholar_request_delay_seconds() -> int:
    return resolve_request_delay_minimum(settings.ingestion_min_request_delay_seconds)


def _fetch_succeeded(fetch_result) -> bool:
    return int(fetch_result.status_code or 0) == 200 and not fetch_result.error


async def fetch_link_candidates_from_scholar_publication_page(
    publication_url: str | None,
) -> ScholarPublicationLinkCandidates | None:
    if not is_scholar_publication_detail_url(publication_url):
        return None
    await wait_for_scholar_slot(min_interval_seconds=float(_scholar_request_delay_seconds()))
    source = LiveScholarSource()
    fetch_result = await source.fetch_publication_html(str(publication_url))
    if not _fetch_succeeded(fetch_result):
        return None
    return extract_link_candidates_from_publication_detail_html(fetch_result.body)
