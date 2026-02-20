from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.services.domains.scholar.parser_constants import (
    MARKER_KEYS,
    PROFILE_ROW_DIRECT_LABEL_TOKENS,
    PROFILE_ROW_PARSER_DIRECT_MARKERS,
    SHOW_MORE_BUTTON_RE,
)
from app.services.domains.scholar.parser_types import PublicationCandidate
from app.services.domains.scholar.parser_utils import (
    attr_class,
    attr_href,
    attr_src,
    build_absolute_scholar_url,
    normalize_space,
    strip_tags,
)


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
            href = attr_href(attrs)
            self._aux_link_stack.append(
                {
                    "depth": 1,
                    "classes": classes,
                    "href": href,
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

    def _capture_direct_download_href(self, link_info: dict[str, Any]) -> None:
        if self.direct_download_href:
            return
        href = link_info.get("href")
        if not href:
            return
        classes = str(link_info.get("classes") or "")
        label = normalize_space("".join(link_info.get("parts") or [])).lower()
        if "gs_ggsd" in classes or "gs_ggs" in classes or "gs_ggsa" in classes:
            self.direct_download_href = href
            return
        label_match = any(token in label for token in PROFILE_ROW_DIRECT_LABEL_TOKENS)
        if self._direct_marker_depth > 0 and label_match:
            self.direct_download_href = href

    def handle_endtag(self, tag: str) -> None:
        if self._title_depth > 0:
            self._title_depth -= 1
        if self._citation_depth > 0:
            self._citation_depth -= 1
        if self._year_depth > 0:
            self._year_depth -= 1
        if self._gray_stack:
            self._gray_stack[-1]["depth"] -= 1
            if self._gray_stack[-1]["depth"] == 0:
                text_value = normalize_space("".join(self._gray_stack[-1]["parts"]))
                if text_value:
                    self.gray_texts.append(text_value)
                self._gray_stack.pop()
        if self._aux_link_stack:
            self._aux_link_stack[-1]["depth"] -= 1
            if self._aux_link_stack[-1]["depth"] == 0:
                link_info = self._aux_link_stack.pop()
                self._capture_direct_download_href(link_info)
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
