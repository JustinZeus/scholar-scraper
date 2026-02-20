from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.services.domains.scholar.parser_constants import AUTHOR_SEARCH_MARKER_KEYS
from app.services.domains.scholar.parser_types import ScholarSearchCandidate
from app.services.domains.scholar.parser_utils import (
    attr_class,
    attr_href,
    attr_src,
    build_absolute_scholar_url,
    normalize_space,
)


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


def count_author_search_markers(html: str) -> dict[str, int]:
    lowered = html.lower()
    return {key: lowered.count(key.lower()) for key in AUTHOR_SEARCH_MARKER_KEYS}
