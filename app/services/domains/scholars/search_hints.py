from __future__ import annotations

from app.db.models import ScholarProfile
from app.services.domains.scholar.parser import ParseState, ParsedAuthorSearchPage
from app.services.domains.scholars.constants import (
    MAX_AUTHOR_SEARCH_LIMIT,
    STATE_REASON_HINTS,
)


def resolve_profile_image(
    profile: ScholarProfile,
    *,
    uploaded_image_url: str | None,
) -> tuple[str | None, str]:
    if profile.profile_image_upload_path and uploaded_image_url:
        return uploaded_image_url, "upload"
    if profile.profile_image_override_url:
        return profile.profile_image_override_url, "override"
    if profile.profile_image_url:
        return profile.profile_image_url, "scraped"
    return None, "none"


def scrape_state_hint(*, state: ParseState, state_reason: str) -> str | None:
    if state not in {ParseState.NETWORK_ERROR, ParseState.BLOCKED_OR_CAPTCHA}:
        return None
    return STATE_REASON_HINTS.get(state_reason)


def _merge_warnings(base: list[str], extra: list[str]) -> list[str]:
    if not extra:
        return sorted(set(base))
    return sorted(set(base + extra))


def _trim_author_search_result(
    parsed: ParsedAuthorSearchPage,
    *,
    limit: int,
    extra_warnings: list[str] | None = None,
    state_reason_override: str | None = None,
) -> ParsedAuthorSearchPage:
    bounded_limit = max(1, min(int(limit), MAX_AUTHOR_SEARCH_LIMIT))
    return ParsedAuthorSearchPage(
        state=parsed.state,
        state_reason=state_reason_override or parsed.state_reason,
        candidates=parsed.candidates[:bounded_limit],
        marker_counts=parsed.marker_counts,
        warnings=_merge_warnings(parsed.warnings, extra_warnings or []),
    )


def _policy_blocked_author_search_result(
    *,
    reason: str,
    warning_codes: list[str],
    limit: int,
) -> ParsedAuthorSearchPage:
    _ = limit
    return ParsedAuthorSearchPage(
        state=ParseState.BLOCKED_OR_CAPTCHA,
        state_reason=reason,
        candidates=[],
        marker_counts={},
        warnings=_merge_warnings([], warning_codes),
    )
