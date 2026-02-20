from __future__ import annotations

from app.services.domains.scholar.parser_constants import (
    BLOCKED_KEYWORDS,
    NETWORK_DNS_ERROR_KEYWORDS,
    NETWORK_TIMEOUT_KEYWORDS,
    NETWORK_TLS_ERROR_KEYWORDS,
    NO_AUTHOR_RESULTS_KEYWORDS,
    NO_RESULTS_KEYWORDS,
)
from app.services.domains.scholar.parser_types import ParseState, PublicationCandidate, ScholarSearchCandidate
from app.services.domains.scholar.source import FetchResult


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
