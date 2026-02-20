from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ParseState(StrEnum):
    OK = "ok"
    NO_RESULTS = "no_results"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    LAYOUT_CHANGED = "layout_changed"
    NETWORK_ERROR = "network_error"


class ScholarParserError(RuntimeError):
    code: str

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ScholarDomInvariantError(ScholarParserError):
    pass


class ScholarMalformedDataError(ScholarParserError):
    pass


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
