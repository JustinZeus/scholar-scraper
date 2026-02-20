from __future__ import annotations

from app.services.domains.scholar.author_rows import (
    ScholarAuthorSearchParser,
    count_author_search_markers,
    parse_scholar_id_from_href,
)
from app.services.domains.scholar.parser_constants import SCRIPT_STYLE_RE
from app.services.domains.scholar.parser_types import (
    ParseState,
    ParsedAuthorSearchPage,
    ParsedProfilePage,
    PublicationCandidate,
    ScholarSearchCandidate,
)
from app.services.domains.scholar.parser_utils import (
    attr_class,
    attr_href,
    attr_src,
    build_absolute_scholar_url,
    normalize_space,
    strip_tags,
)
from app.services.domains.scholar.profile_rows import (
    ScholarRowParser,
    count_markers,
    extract_articles_range,
    extract_profile_image_url,
    extract_profile_name,
    extract_rows,
    has_operation_error_banner,
    has_show_more_button,
    parse_citation_count,
    parse_cluster_id_from_href,
    parse_publications,
    parse_year,
)
from app.services.domains.scholar.source import FetchResult
from app.services.domains.scholar.state_detection import (
    classify_block_or_captcha_reason,
    classify_network_error_reason,
    detect_author_search_state,
    detect_state,
)


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
