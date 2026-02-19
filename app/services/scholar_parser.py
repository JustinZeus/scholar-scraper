from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from app.services.scholar_source import FetchResult

BLOCKED_KEYWORDS = [
    "unusual traffic",
    "sorry/index",
    "not a robot",
    "our systems have detected",
    "automated queries",
    "recaptcha",
    "captcha",
]

NO_RESULTS_KEYWORDS = [
    "didn't match any articles",
    "did not match any articles",
    "no articles",
    "no documents",
]

NO_AUTHOR_RESULTS_KEYWORDS = [
    "didn't match any user profiles",
    "did not match any user profiles",
    "didn't match any scholars",
    "did not match any scholars",
    "no user profiles",
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

AUTHOR_SEARCH_MARKER_KEYS = [
    "gsc_1usr",
    "gs_ai_name",
    "gs_ai_aff",
    "gs_ai_eml",
    "gs_ai_cby",
    "gs_ai_one_int",
]

NETWORK_DNS_ERROR_KEYWORDS = [
    "temporary failure in name resolution",
    "name or service not known",
    "nodename nor servname provided",
    "getaddrinfo failed",
]

NETWORK_TIMEOUT_KEYWORDS = [
    "timed out",
    "timeout",
]

NETWORK_TLS_ERROR_KEYWORDS = [
    "ssl",
    "tls",
    "certificate verify failed",
]

TAG_RE = re.compile(r"<[^>]+>", re.S)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
SHOW_MORE_BUTTON_RE = re.compile(
    r"<button\b[^>]*\bid\s*=\s*['\"]gsc_bpf_more['\"][^>]*>",
    re.I | re.S,
)
PROFILE_ROW_PARSER_DIRECT_MARKERS = (
    "gs_ggs",
    "gs_ggsd",
    "gs_ggsa",
    "gs_or_ggsm",
)
PROFILE_ROW_DIRECT_LABEL_TOKENS = (
    "pdf",
    "[pdf]",
    "full text",
    "download",
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
    pdf_url: str | None


@dataclass(frozen=True)
class ScholarSearchCandidate:
    scholar_id: str
    display_name: str
    affiliation: str | None
    email_domain: str | None
    cited_by_count: int | None
    interests: list[str]
    profile_url: str
    profile_image_url: str | None


@dataclass(frozen=True)
class ParsedProfilePage:
    state: ParseState
    state_reason: str
    profile_name: str | None
    profile_image_url: str | None
    publications: list[PublicationCandidate]
    marker_counts: dict[str, int]
    warnings: list[str]
    has_show_more_button: bool
    has_operation_error_banner: bool
    articles_range: str | None


@dataclass(frozen=True)
class ParsedAuthorSearchPage:
    state: ParseState
    state_reason: str
    candidates: list[ScholarSearchCandidate]
    marker_counts: dict[str, int]
    warnings: list[str]


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


def attr_src(attrs: list[tuple[str, str | None]]) -> str | None:
    for name, raw_value in attrs:
        if name.lower() == "src":
            return raw_value
    return None


def build_absolute_scholar_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    return urljoin("https://scholar.google.com", path_or_url)


class ScholarRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_href: str | None = None
        self.direct_download_href: str | None = None
        self.title_parts: list[str] = []
        self.citation_parts: list[str] = []
        self.year_parts: list[str] = []
        self.gray_texts: list[str] = []

        self._title_depth = 0
        self._citation_depth = 0
        self._year_depth = 0
        self._gray_stack: list[dict[str, Any]] = []
        self._direct_marker_depth = 0
        self._aux_link_stack: list[dict[str, Any]] = []

    @staticmethod
    def _contains_direct_marker(classes: str) -> bool:
        lowered = classes.lower()
        return any(marker in lowered for marker in PROFILE_ROW_PARSER_DIRECT_MARKERS)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._title_depth > 0:
            self._title_depth += 1
        if self._citation_depth > 0:
            self._citation_depth += 1
        if self._year_depth > 0:
            self._year_depth += 1
        if self._gray_stack:
            self._gray_stack[-1]["depth"] += 1
        if self._direct_marker_depth > 0:
            self._direct_marker_depth += 1
        if self._aux_link_stack:
            self._aux_link_stack[-1]["depth"] += 1

        classes = attr_class(attrs)
        if tag in {"div", "span"} and self._contains_direct_marker(classes):
            self._direct_marker_depth = 1

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

        if tag == "a":
            self._aux_link_stack.append(
                {
                    "depth": 1,
                    "href": attr_href(attrs),
                    "classes": classes,
                    "parts": [],
                }
            )

    def handle_data(self, data: str) -> None:
        if self._title_depth > 0:
            self.title_parts.append(data)
        if self._citation_depth > 0:
            self.citation_parts.append(data)
        if self._year_depth > 0:
            self.year_parts.append(data)
        if self._gray_stack:
            self._gray_stack[-1]["parts"].append(data)
        if self._aux_link_stack:
            self._aux_link_stack[-1]["parts"].append(data)

    def _capture_direct_download_href(self, link: dict[str, Any]) -> None:
        if self.direct_download_href:
            return
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            return
        label = normalize_space("".join(link.get("parts", []))).lower()
        classes = str(link.get("classes", "")).lower()
        label_match = any(token in label for token in PROFILE_ROW_DIRECT_LABEL_TOKENS)
        marker_match = self._contains_direct_marker(classes) or self._direct_marker_depth > 0
        if label_match or marker_match:
            self.direct_download_href = href.strip()

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
        if self._aux_link_stack:
            self._aux_link_stack[-1]["depth"] -= 1
            if self._aux_link_stack[-1]["depth"] == 0:
                self._capture_direct_download_href(self._aux_link_stack[-1])
                self._aux_link_stack.pop()
        if self._direct_marker_depth > 0:
            self._direct_marker_depth -= 1


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


def parse_scholar_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    user_values = query.get("user")
    if not user_values:
        return None
    candidate = user_values[0].strip()
    return candidate or None


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


def _parse_publication_row(row_html: str) -> tuple[PublicationCandidate | None, list[str]]:
    parser = ScholarRowParser()
    parser.feed(row_html)
    warnings: list[str] = []
    title = normalize_space("".join(parser.title_parts))
    if not title:
        warnings.append("row_missing_title")
        return None, warnings
    if not parser.title_href:
        warnings.append("row_missing_title_href")

    citation_text = normalize_space(" ".join(parser.citation_parts))
    citation_count = parse_citation_count(parser.citation_parts)
    if citation_text and citation_count is None:
        warnings.append("layout_row_citation_unparseable")

    year_text = normalize_space(" ".join(parser.year_parts))
    year = parse_year(parser.year_parts)
    if year_text and year is None:
        warnings.append("layout_row_year_unparseable")

    authors_text = parser.gray_texts[0] if len(parser.gray_texts) > 0 else None
    venue_text = parser.gray_texts[1] if len(parser.gray_texts) > 1 else None
    return (
        PublicationCandidate(
            title=title,
            title_url=parser.title_href,
            cluster_id=parse_cluster_id_from_href(parser.title_href),
            year=year,
            citation_count=citation_count,
            authors_text=authors_text,
            venue_text=venue_text,
            pdf_url=build_absolute_scholar_url(parser.direct_download_href),
        ),
        warnings,
    )


def parse_publications(html: str) -> tuple[list[PublicationCandidate], list[str]]:
    rows = extract_rows(html)
    warnings: list[str] = []
    publications: list[PublicationCandidate] = []

    for row_html in rows:
        publication, row_warnings = _parse_publication_row(row_html)
        warnings.extend(row_warnings)
        if publication is None:
            continue
        publications.append(publication)

    if not rows:
        warnings.append("no_rows_detected")
    if rows and not publications:
        warnings.append("layout_all_rows_unparseable")

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


def extract_profile_image_url(html: str) -> str | None:
    og_image_pattern = re.compile(
        r"<meta[^>]+property=['\"]og:image['\"][^>]+content=['\"]([^'\"]+)['\"][^>]*>",
        re.I | re.S,
    )
    og_match = og_image_pattern.search(html)
    if og_match:
        value = normalize_space(og_match.group(1))
        absolute = build_absolute_scholar_url(value)
        if absolute:
            return absolute

    image_pattern = re.compile(
        r"<img[^>]*\bid=['\"]gsc_prf_pup-img['\"][^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*>",
        re.I | re.S,
    )
    image_match = image_pattern.search(html)
    if not image_match:
        return None

    value = normalize_space(image_match.group(1))
    return build_absolute_scholar_url(value)


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


def count_author_search_markers(html: str) -> dict[str, int]:
    lowered = html.lower()
    return {key: lowered.count(key.lower()) for key in AUTHOR_SEARCH_MARKER_KEYS}


def _extract_verified_email_domain(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"verified email at\s+(.+)$", value.strip(), re.I)
    if not match:
        return None
    domain = normalize_space(match.group(1))
    return domain or None


class ScholarAuthorSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[ScholarSearchCandidate] = []
        self._candidate: dict[str, Any] | None = None

    def _begin_candidate(self) -> None:
        self._candidate = {
            "depth": 1,
            "name_href": None,
            "name_parts": [],
            "aff_depth": 0,
            "aff_parts": [],
            "name_depth": 0,
            "eml_depth": 0,
            "eml_parts": [],
            "cby_depth": 0,
            "cby_parts": [],
            "interest_depth": 0,
            "interest_parts": [],
            "interests": [],
            "image_src": None,
        }

    def _increment_capture_depths(self) -> None:
        if self._candidate is None:
            return
        for key in ("name_depth", "aff_depth", "eml_depth", "cby_depth", "interest_depth"):
            if self._candidate[key] > 0:
                self._candidate[key] += 1

    def _finalize_candidate(self) -> None:
        if self._candidate is None:
            return

        name = normalize_space("".join(self._candidate["name_parts"]))
        scholar_id = parse_scholar_id_from_href(self._candidate["name_href"])
        if not name or not scholar_id:
            return

        affiliation = normalize_space("".join(self._candidate["aff_parts"])) or None
        email_domain = _extract_verified_email_domain(
            normalize_space("".join(self._candidate["eml_parts"])) or None
        )
        cited_by_text = normalize_space("".join(self._candidate["cby_parts"]))
        cited_by_match = re.search(r"\d+", cited_by_text)
        cited_by_count = int(cited_by_match.group(0)) if cited_by_match else None

        seen_interests: set[str] = set()
        interests: list[str] = []
        for interest in self._candidate["interests"]:
            normalized = normalize_space(interest)
            if not normalized or normalized in seen_interests:
                continue
            seen_interests.add(normalized)
            interests.append(normalized)

        profile_url = build_absolute_scholar_url(self._candidate["name_href"])
        if not profile_url:
            profile_url = (
                "https://scholar.google.com/citations"
                f"?hl=en&user={scholar_id}"
            )

        self.candidates.append(
            ScholarSearchCandidate(
                scholar_id=scholar_id,
                display_name=name,
                affiliation=affiliation,
                email_domain=email_domain,
                cited_by_count=cited_by_count,
                interests=interests,
                profile_url=profile_url,
                profile_image_url=build_absolute_scholar_url(self._candidate["image_src"]),
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = attr_class(attrs)

        if self._candidate is None:
            if tag == "div" and "gsc_1usr" in classes:
                self._begin_candidate()
            return

        self._candidate["depth"] += 1
        self._increment_capture_depths()

        if tag == "a" and "gs_ai_name" in classes:
            self._candidate["name_depth"] = 1
            self._candidate["name_href"] = attr_href(attrs)
            return

        if tag == "div" and "gs_ai_aff" in classes:
            self._candidate["aff_depth"] = 1
            return

        if tag == "div" and "gs_ai_eml" in classes:
            self._candidate["eml_depth"] = 1
            return

        if tag == "div" and "gs_ai_cby" in classes:
            self._candidate["cby_depth"] = 1
            return

        if tag == "a" and "gs_ai_one_int" in classes:
            self._candidate["interest_depth"] = 1
            self._candidate["interest_parts"] = []
            return

        if tag == "img" and self._candidate["image_src"] is None:
            self._candidate["image_src"] = attr_src(attrs)

    def handle_data(self, data: str) -> None:
        if self._candidate is None:
            return
        if self._candidate["name_depth"] > 0:
            self._candidate["name_parts"].append(data)
        if self._candidate["aff_depth"] > 0:
            self._candidate["aff_parts"].append(data)
        if self._candidate["eml_depth"] > 0:
            self._candidate["eml_parts"].append(data)
        if self._candidate["cby_depth"] > 0:
            self._candidate["cby_parts"].append(data)
        if self._candidate["interest_depth"] > 0:
            self._candidate["interest_parts"].append(data)

    def _decrement_capture_depth(self, key: str) -> bool:
        if self._candidate is None:
            return False
        if self._candidate[key] <= 0:
            return False
        self._candidate[key] -= 1
        return self._candidate[key] == 0

    def handle_endtag(self, _tag: str) -> None:
        if self._candidate is None:
            return

        interest_closed = self._decrement_capture_depth("interest_depth")
        self._decrement_capture_depth("name_depth")
        self._decrement_capture_depth("aff_depth")
        self._decrement_capture_depth("eml_depth")
        self._decrement_capture_depth("cby_depth")

        if interest_closed:
            interest_text = normalize_space("".join(self._candidate["interest_parts"]))
            if interest_text:
                self._candidate["interests"].append(interest_text)
            self._candidate["interest_parts"] = []

        self._candidate["depth"] -= 1
        if self._candidate["depth"] > 0:
            return

        self._finalize_candidate()
        self._candidate = None


def classify_network_error_reason(fetch_error: str | None) -> str:
    lowered = (fetch_error or "").lower()
    if lowered:
        if any(keyword in lowered for keyword in NETWORK_DNS_ERROR_KEYWORDS):
            return "network_dns_resolution_failed"
        if any(keyword in lowered for keyword in NETWORK_TIMEOUT_KEYWORDS):
            return "network_timeout"
        if any(keyword in lowered for keyword in NETWORK_TLS_ERROR_KEYWORDS):
            return "network_tls_error"
        if "connection reset" in lowered:
            return "network_connection_reset"
        if "connection refused" in lowered:
            return "network_connection_refused"
        if "network is unreachable" in lowered:
            return "network_unreachable"
    return "network_error_missing_status_code"


def classify_block_or_captcha_reason(
    *,
    status_code: int,
    final_url: str,
    body_lowered: str,
) -> str | None:
    if "accounts.google.com" in final_url and ("signin" in final_url or "servicelogin" in final_url):
        return "blocked_accounts_redirect"
    if status_code == 429:
        return "blocked_http_429_rate_limited"
    if status_code == 403:
        if "recaptcha" in body_lowered or "captcha" in body_lowered or "sorry/index" in final_url:
            return "blocked_http_403_captcha_challenge"
        return "blocked_http_403_forbidden"
    if "sorry/index" in final_url or "sorry/index" in body_lowered:
        return "blocked_google_sorry_challenge"
    if "our systems have detected" in body_lowered or "unusual traffic" in body_lowered:
        return "blocked_unusual_traffic_detected"
    if "automated queries" in body_lowered:
        return "blocked_automated_queries_detected"
    if "not a robot" in body_lowered:
        return "blocked_not_a_robot_challenge"
    if "recaptcha" in body_lowered:
        return "blocked_recaptcha_challenge"
    if "captcha" in body_lowered:
        return "blocked_captcha_challenge"
    if any(keyword in body_lowered for keyword in BLOCKED_KEYWORDS):
        return "blocked_keyword_detected"
    return None


def _warnings_contain(warnings: list[str], code: str) -> bool:
    return any(item == code for item in warnings)


def _has_layout_row_failure(marker_counts: dict[str, int], warnings: list[str]) -> bool:
    if _warnings_contain(warnings, "layout_all_rows_unparseable"):
        return True
    if marker_counts.get("gsc_a_tr", 0) <= 0:
        return False
    if _warnings_contain(warnings, "row_missing_title"):
        return True
    return marker_counts.get("gsc_a_at", 0) <= 0


def _first_layout_warning(warnings: list[str]) -> str | None:
    for warning in warnings:
        if warning.startswith("layout_"):
            return warning
    return None


def detect_state(
    fetch_result: FetchResult,
    publications: list[PublicationCandidate],
    marker_counts: dict[str, int],
    *,
    warnings: list[str],
    has_show_more_button_flag: bool,
    articles_range: str | None,
    visible_text: str,
) -> tuple[ParseState, str]:
    if fetch_result.status_code is None:
        return ParseState.NETWORK_ERROR, classify_network_error_reason(fetch_result.error)

    lowered = fetch_result.body.lower()
    final = (fetch_result.final_url or "").lower()
    status_code = int(fetch_result.status_code)

    block_reason = classify_block_or_captcha_reason(
        status_code=status_code,
        final_url=final,
        body_lowered=lowered,
    )
    if block_reason is not None:
        return ParseState.BLOCKED_OR_CAPTCHA, block_reason

    if not publications and any(keyword in visible_text for keyword in NO_RESULTS_KEYWORDS):
        return ParseState.NO_RESULTS, "no_results_keyword_detected"

    layout_warning = _first_layout_warning(warnings)
    if layout_warning is not None:
        return ParseState.LAYOUT_CHANGED, layout_warning

    if _has_layout_row_failure(marker_counts, warnings):
        return ParseState.LAYOUT_CHANGED, "layout_publication_rows_unparseable"

    if has_show_more_button_flag and not articles_range:
        return ParseState.LAYOUT_CHANGED, "layout_show_more_without_articles_range"

    if not publications:
        has_profile_markers = marker_counts.get("gsc_prf_in", 0) > 0
        has_table_markers = marker_counts.get("gsc_a_tr", 0) > 0 or marker_counts.get("gsc_a_at", 0) > 0
        if not has_profile_markers and not has_table_markers:
            return ParseState.LAYOUT_CHANGED, "layout_markers_missing"
        return ParseState.OK, "no_rows_with_known_markers"

    return ParseState.OK, "publications_extracted"


def detect_author_search_state(
    fetch_result: FetchResult,
    candidates: list[ScholarSearchCandidate],
    marker_counts: dict[str, int],
    *,
    visible_text: str,
) -> tuple[ParseState, str]:
    if fetch_result.status_code is None:
        return ParseState.NETWORK_ERROR, classify_network_error_reason(fetch_result.error)

    lowered = fetch_result.body.lower()
    final = (fetch_result.final_url or "").lower()
    status_code = int(fetch_result.status_code)

    block_reason = classify_block_or_captcha_reason(
        status_code=status_code,
        final_url=final,
        body_lowered=lowered,
    )
    if block_reason is not None:
        return ParseState.BLOCKED_OR_CAPTCHA, block_reason

    if not candidates and any(keyword in visible_text for keyword in NO_AUTHOR_RESULTS_KEYWORDS):
        return ParseState.NO_RESULTS, "no_results_keyword_detected"

    if not candidates:
        has_search_markers = marker_counts.get("gsc_1usr", 0) > 0 or marker_counts.get("gs_ai_name", 0) > 0
        if not has_search_markers:
            return ParseState.NO_RESULTS, "no_search_candidates_detected"
        return ParseState.LAYOUT_CHANGED, "layout_author_candidates_unparseable"

    return ParseState.OK, "author_candidates_extracted"


def parse_profile_page(fetch_result: FetchResult) -> ParsedProfilePage:
    publications, warnings = parse_publications(fetch_result.body)
    marker_counts = count_markers(fetch_result.body)
    visible_text = strip_tags(SCRIPT_STYLE_RE.sub(" ", fetch_result.body)).lower()

    show_more = has_show_more_button(fetch_result.body)
    operation_error_banner = has_operation_error_banner(fetch_result.body)
    articles_range = extract_articles_range(fetch_result.body)

    if show_more:
        warnings.append("possible_partial_page_show_more_present")
    if operation_error_banner:
        warnings.append("operation_error_banner_present")

    warnings = sorted(set(warnings))

    state, state_reason = detect_state(
        fetch_result,
        publications,
        marker_counts,
        warnings=warnings,
        has_show_more_button_flag=show_more,
        articles_range=articles_range,
        visible_text=visible_text,
    )

    return ParsedProfilePage(
        state=state,
        state_reason=state_reason,
        profile_name=extract_profile_name(fetch_result.body),
        profile_image_url=extract_profile_image_url(fetch_result.body),
        publications=publications,
        marker_counts=marker_counts,
        warnings=warnings,
        has_show_more_button=show_more,
        has_operation_error_banner=operation_error_banner,
        articles_range=articles_range,
    )


def parse_author_search_page(fetch_result: FetchResult) -> ParsedAuthorSearchPage:
    parser = ScholarAuthorSearchParser()
    parser.feed(fetch_result.body)

    marker_counts = count_author_search_markers(fetch_result.body)
    visible_text = strip_tags(SCRIPT_STYLE_RE.sub(" ", fetch_result.body)).lower()
    warnings: list[str] = []
    if not parser.candidates:
        warnings.append("no_author_candidates_detected")

    state, state_reason = detect_author_search_state(
        fetch_result,
        parser.candidates,
        marker_counts,
        visible_text=visible_text,
    )

    return ParsedAuthorSearchPage(
        state=state,
        state_reason=state_reason,
        candidates=parser.candidates,
        marker_counts=marker_counts,
        warnings=warnings,
    )
