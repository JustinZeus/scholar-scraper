from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.services.scholar_source import FetchResult

BLOCKED_KEYWORDS = [
    "unusual traffic",
    "sorry/index",
    "not a robot",
    "our systems have detected",
    "automated queries",
]

NO_RESULTS_KEYWORDS = [
    "didn't match any articles",
    "did not match any articles",
    "no articles",
    "no documents",
]

MARKER_KEYS = [
    "gsc_a_tr",
    "gsc_a_at",
    "gsc_a_ac",
    "gsc_a_h",
    "gsc_a_y",
    "gs_gray",
    "gsc_prf_in",
    "gsc_rsb_st",
]

TAG_RE = re.compile(r"<[^>]+>", re.S)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
SHOW_MORE_BUTTON_RE = re.compile(
    r"<button\b[^>]*\bid\s*=\s*['\"]gsc_bpf_more['\"][^>]*>",
    re.I | re.S,
)


class ParseState(StrEnum):
    OK = "ok"
    NO_RESULTS = "no_results"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    LAYOUT_CHANGED = "layout_changed"
    NETWORK_ERROR = "network_error"


@dataclass(frozen=True)
class PublicationCandidate:
    title: str
    title_url: str | None
    cluster_id: str | None
    year: int | None
    citation_count: int | None
    authors_text: str | None
    venue_text: str | None


@dataclass(frozen=True)
class ParsedProfilePage:
    state: ParseState
    state_reason: str
    profile_name: str | None
    publications: list[PublicationCandidate]
    marker_counts: dict[str, int]
    warnings: list[str]
    has_show_more_button: bool
    has_operation_error_banner: bool
    articles_range: str | None


def normalize_space(value: str) -> str:
    return " ".join(unescape(value).split())


def strip_tags(value: str) -> str:
    return normalize_space(TAG_RE.sub(" ", value))


def attr_class(attrs: list[tuple[str, str | None]]) -> str:
    for name, raw_value in attrs:
        if name.lower() == "class":
            return raw_value or ""
    return ""


def attr_href(attrs: list[tuple[str, str | None]]) -> str | None:
    for name, raw_value in attrs:
        if name.lower() == "href":
            return raw_value
    return None


class ScholarRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_href: str | None = None
        self.title_parts: list[str] = []
        self.citation_parts: list[str] = []
        self.year_parts: list[str] = []
        self.gray_texts: list[str] = []

        self._title_depth = 0
        self._citation_depth = 0
        self._year_depth = 0
        self._gray_stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._title_depth > 0:
            self._title_depth += 1
        if self._citation_depth > 0:
            self._citation_depth += 1
        if self._year_depth > 0:
            self._year_depth += 1
        if self._gray_stack:
            self._gray_stack[-1]["depth"] += 1

        classes = attr_class(attrs)

        if tag == "a" and "gsc_a_at" in classes:
            self._title_depth = 1
            self.title_href = attr_href(attrs)
            return

        if tag == "a" and "gsc_a_ac" in classes:
            self._citation_depth = 1
            return

        if tag in {"span", "a"} and ("gsc_a_h" in classes or "gsc_a_y" in classes):
            self._year_depth = 1
            return

        if tag == "div" and "gs_gray" in classes:
            self._gray_stack.append({"depth": 1, "parts": []})
            return

    def handle_data(self, data: str) -> None:
        if self._title_depth > 0:
            self.title_parts.append(data)
        if self._citation_depth > 0:
            self.citation_parts.append(data)
        if self._year_depth > 0:
            self.year_parts.append(data)
        if self._gray_stack:
            self._gray_stack[-1]["parts"].append(data)

    def handle_endtag(self, _tag: str) -> None:
        if self._title_depth > 0:
            self._title_depth -= 1
        if self._citation_depth > 0:
            self._citation_depth -= 1
        if self._year_depth > 0:
            self._year_depth -= 1
        if self._gray_stack:
            self._gray_stack[-1]["depth"] -= 1
            if self._gray_stack[-1]["depth"] == 0:
                text = normalize_space("".join(self._gray_stack[-1]["parts"]))
                if text:
                    self.gray_texts.append(text)
                self._gray_stack.pop()


def extract_rows(html: str) -> list[str]:
    pattern = re.compile(
        r"<tr\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bgsc_a_tr\b[^'\"]*['\"])[^>]*>(.*?)</tr>",
        re.I | re.S,
    )
    return [match.group(1) for match in pattern.finditer(html)]


def parse_cluster_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    query = parse_qs(parsed.query)

    citation_for_view = query.get("citation_for_view")
    if citation_for_view:
        token = citation_for_view[0].strip()
        if token:
            if ":" in token:
                return token.rsplit(":", 1)[-1] or None
            return token

    cluster = query.get("cluster")
    if cluster:
        token = cluster[0].strip()
        if token:
            return token
    return None


def parse_year(parts: list[str]) -> int | None:
    text = normalize_space(" ".join(parts))
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def parse_citation_count(parts: list[str]) -> int | None:
    text = normalize_space(" ".join(parts))
    if not text:
        return 0
    match = re.search(r"\d+", text)
    if not match:
        return None
    return int(match.group(0))


def parse_publications(html: str) -> tuple[list[PublicationCandidate], list[str]]:
    rows = extract_rows(html)
    warnings: list[str] = []
    publications: list[PublicationCandidate] = []

    for row_html in rows:
        parser = ScholarRowParser()
        parser.feed(row_html)

        title = normalize_space("".join(parser.title_parts))
        if not title:
            warnings.append("row_missing_title")
            continue

        authors_text = parser.gray_texts[0] if len(parser.gray_texts) > 0 else None
        venue_text = parser.gray_texts[1] if len(parser.gray_texts) > 1 else None

        publications.append(
            PublicationCandidate(
                title=title,
                title_url=parser.title_href,
                cluster_id=parse_cluster_id_from_href(parser.title_href),
                year=parse_year(parser.year_parts),
                citation_count=parse_citation_count(parser.citation_parts),
                authors_text=authors_text,
                venue_text=venue_text,
            )
        )

    if not rows:
        warnings.append("no_rows_detected")

    return publications, sorted(set(warnings))


def extract_profile_name(html: str) -> str | None:
    pattern = re.compile(
        r"<[^>]*\bid\s*=\s*['\"]gsc_prf_in['\"][^>]*>(.*?)</[^>]+>",
        re.I | re.S,
    )
    match = pattern.search(html)
    if not match:
        return None
    value = strip_tags(match.group(1))
    return value or None


def extract_articles_range(html: str) -> str | None:
    pattern = re.compile(
        r"<[^>]*\bid\s*=\s*['\"]gsc_a_nn['\"][^>]*>(.*?)</[^>]+>",
        re.I | re.S,
    )
    match = pattern.search(html)
    if not match:
        return None
    value = strip_tags(match.group(1))
    return value or None


def has_show_more_button(html: str) -> bool:
    match = SHOW_MORE_BUTTON_RE.search(html)
    if match is None:
        return False

    button_tag = match.group(0).lower()
    if "disabled" in button_tag:
        return False
    if 'aria-disabled="true"' in button_tag or "aria-disabled='true'" in button_tag:
        return False
    if "gs_dis" in button_tag:
        return False
    return True


def has_operation_error_banner(html: str) -> bool:
    lowered = html.lower()
    if "id=\"gsc_a_err\"" not in lowered and "id='gsc_a_err'" not in lowered:
        return False
    return "can't perform the operation now" in lowered or "cannot perform the operation now" in lowered


def count_markers(html: str) -> dict[str, int]:
    lowered = html.lower()
    return {key: lowered.count(key.lower()) for key in MARKER_KEYS}


def detect_state(
    fetch_result: FetchResult,
    publications: list[PublicationCandidate],
    marker_counts: dict[str, int],
    *,
    visible_text: str,
) -> tuple[ParseState, str]:
    if fetch_result.status_code is None:
        return ParseState.NETWORK_ERROR, "network_error_missing_status_code"

    lowered = fetch_result.body.lower()
    final = (fetch_result.final_url or "").lower()

    if "accounts.google.com" in final and ("signin" in final or "servicelogin" in final):
        return ParseState.BLOCKED_OR_CAPTCHA, "blocked_accounts_redirect"
    if any(keyword in lowered for keyword in BLOCKED_KEYWORDS) or "sorry/index" in final:
        return ParseState.BLOCKED_OR_CAPTCHA, "blocked_keyword_detected"

    if not publications and any(keyword in visible_text for keyword in NO_RESULTS_KEYWORDS):
        return ParseState.NO_RESULTS, "no_results_keyword_detected"

    if not publications:
        has_profile_markers = marker_counts.get("gsc_prf_in", 0) > 0
        has_table_markers = marker_counts.get("gsc_a_tr", 0) > 0 or marker_counts.get("gsc_a_at", 0) > 0
        if not has_profile_markers and not has_table_markers:
            return ParseState.LAYOUT_CHANGED, "layout_markers_missing"
        return ParseState.OK, "no_rows_with_known_markers"

    return ParseState.OK, "publications_extracted"


def parse_profile_page(fetch_result: FetchResult) -> ParsedProfilePage:
    publications, warnings = parse_publications(fetch_result.body)
    marker_counts = count_markers(fetch_result.body)
    visible_text = strip_tags(SCRIPT_STYLE_RE.sub(" ", fetch_result.body)).lower()

    show_more = has_show_more_button(fetch_result.body)
    operation_error_banner = has_operation_error_banner(fetch_result.body)

    if show_more:
        warnings.append("possible_partial_page_show_more_present")
    if operation_error_banner:
        warnings.append("operation_error_banner_present")

    warnings = sorted(set(warnings))

    state, state_reason = detect_state(
        fetch_result,
        publications,
        marker_counts,
        visible_text=visible_text,
    )

    return ParsedProfilePage(
        state=state,
        state_reason=state_reason,
        profile_name=extract_profile_name(fetch_result.body),
        publications=publications,
        marker_counts=marker_counts,
        warnings=warnings,
        has_show_more_button=show_more,
        has_operation_error_banner=operation_error_banner,
        articles_range=extract_articles_range(fetch_result.body),
    )
