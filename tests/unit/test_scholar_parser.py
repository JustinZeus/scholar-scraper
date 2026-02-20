from __future__ import annotations

from pathlib import Path

import pytest

from app.services.domains.scholar.parser import (
    ParseState,
    ScholarDomInvariantError,
    parse_author_search_page,
    parse_profile_page,
)
from app.services.domains.scholar.source import FetchResult


def _fixture(name: str) -> str:
    path = Path("tests/fixtures/scholar") / name
    return path.read_text(encoding="utf-8")


def _regression_fixture(name: str) -> str:
    path = Path("tests/fixtures/scholar/regression") / name
    return path.read_text(encoding="utf-8")


def test_parse_profile_page_extracts_core_fields_from_fixture() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=amIMrIEAAAAJ",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=amIMrIEAAAAJ",
        body=_fixture("profile_ok_amIMrIEAAAAJ.html"),
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.state_reason == "publications_extracted"
    assert parsed.profile_name == "Bangar Raju Cherukuri"
    assert parsed.profile_image_url
    assert parsed.profile_image_url.startswith("http")
    assert len(parsed.publications) >= 10
    assert parsed.has_show_more_button is True
    assert parsed.articles_range is not None
    first = parsed.publications[0]
    assert first.title
    assert first.cluster_id
    assert first.citation_count is not None


def test_parse_profile_page_classifies_accounts_redirect_as_blocked() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=AAAAAAAAAAAA",
        status_code=200,
        final_url="https://accounts.google.com/v3/signin/identifier?continue=...",
        body="<html><body>Sign in</body></html>",
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.BLOCKED_OR_CAPTCHA
    assert parsed.state_reason == "blocked_accounts_redirect"
    assert len(parsed.publications) == 0


def test_parse_profile_page_handles_missing_optional_metadata() -> None:
    html = """
    <html>
      <div id="gsc_prf_in">Test Author</div>
      <span id="gsc_a_nn">Articles 1-1</span>
      <table>
        <tbody id="gsc_a_b">
          <tr class="gsc_a_tr">
            <td class="gsc_a_t">
              <a class="gsc_a_at" href="/citations?view_op=view_citation&citation_for_view=abc:def123">A Test Paper</a>
              <div class="gs_gray">A Person</div>
            </td>
            <td class="gsc_a_c"><a class="gsc_a_ac">7</a></td>
            <td class="gsc_a_y"><span class="gsc_a_h"></span></td>
          </tr>
        </tbody>
      </table>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body=html,
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.state_reason == "publications_extracted"
    assert len(parsed.publications) == 1
    publication = parsed.publications[0]
    assert publication.cluster_id == "cfv:abc:def123"
    assert publication.year is None
    assert publication.venue_text is None


def test_parse_profile_page_parses_comma_formatted_citation_counts() -> None:
    html = """
    <html>
      <div id="gsc_prf_in">Citation Formatting Test</div>
      <span id="gsc_a_nn">Articles 1-1</span>
      <table>
        <tbody id="gsc_a_b">
          <tr class="gsc_a_tr">
            <td class="gsc_a_t">
              <a class="gsc_a_at" href="/citations?view_op=view_citation&citation_for_view=abc:def123">Paper</a>
            </td>
            <td class="gsc_a_c"><a class="gsc_a_ac">Cited by 1,234</a></td>
            <td class="gsc_a_y"><span class="gsc_a_h">2024</span></td>
          </tr>
        </tbody>
      </table>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body=html,
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert len(parsed.publications) == 1
    assert parsed.publications[0].citation_count == 1234


def test_parse_profile_page_ignores_direct_pdf_link_markup() -> None:
    html = """
    <html>
      <div id="gsc_prf_in">Direct PDF Test</div>
      <span id="gsc_a_nn">Articles 1-1</span>
      <table>
        <tbody id="gsc_a_b">
          <tr class="gsc_a_tr">
            <td class="gsc_a_t">
              <a class="gsc_a_at" href="/citations?view_op=view_citation&citation_for_view=abc:def999">Paper</a>
              <div class="gs_ggs gs_fl">
                <a href="https://example.org/paper.pdf">[PDF]</a>
              </div>
            </td>
            <td class="gsc_a_c"><a class="gsc_a_ac">3</a></td>
            <td class="gsc_a_y"><span class="gsc_a_h">2025</span></td>
          </tr>
        </tbody>
      </table>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body=html,
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert len(parsed.publications) == 1
    assert parsed.publications[0].pdf_url is None


def test_parse_profile_page_fails_fast_when_citation_markup_is_unparseable() -> None:
    html = """
    <html>
      <div id="gsc_prf_in">Citation Parse Drift</div>
      <span id="gsc_a_nn">Articles 1-1</span>
      <table>
        <tbody id="gsc_a_b">
          <tr class="gsc_a_tr">
            <td class="gsc_a_t">
              <a class="gsc_a_at" href="/citations?view_op=view_citation&citation_for_view=abc:def777">Paper</a>
            </td>
            <td class="gsc_a_c"><a class="gsc_a_ac">Cited by none</a></td>
            <td class="gsc_a_y"><span class="gsc_a_h">2025</span></td>
          </tr>
        </tbody>
      </table>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body=html,
        error=None,
    )

    with pytest.raises(ScholarDomInvariantError) as exc:
        parse_profile_page(fetch_result)
    assert exc.value.code == "layout_row_citation_unparseable"


def test_parse_profile_page_detects_layout_change_when_markers_absent() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body="<html><body><h1>Unexpected page</h1></body></html>",
        error=None,
    )

    with pytest.raises(ScholarDomInvariantError) as exc:
        parse_profile_page(fetch_result)
    assert exc.value.code == "layout_markers_missing"


def test_parse_profile_page_reports_network_reason_when_status_missing() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=None,
        final_url=None,
        body="",
        error="timed out",
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.NETWORK_ERROR
    assert parsed.state_reason == "network_timeout"


def test_parse_profile_page_reports_dns_network_reason_when_status_missing() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=None,
        final_url=None,
        body="",
        error="<urlopen error [Errno -3] Temporary failure in name resolution>",
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.NETWORK_ERROR
    assert parsed.state_reason == "network_dns_resolution_failed"


def test_parse_profile_page_ignores_no_results_keyword_inside_script_blocks() -> None:
    html = """
    <html>
      <script>
        const message = "didn't match any articles";
      </script>
      <div id="gsc_prf_in">Scripted Author</div>
      <table><tbody id="gsc_a_b"></tbody></table>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body=html,
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.state_reason == "no_rows_with_known_markers"


def test_parse_profile_page_treats_disabled_show_more_button_as_absent() -> None:
    html = """
    <html>
      <div id="gsc_prf_in">Disabled Show More</div>
      <span id="gsc_a_nn">Articles 1-1</span>
      <table><tbody id="gsc_a_b">
        <tr class="gsc_a_tr">
          <td class="gsc_a_t">
            <a class="gsc_a_at" href="/citations?view_op=view_citation&citation_for_view=abc:def">Paper</a>
          </td>
          <td class="gsc_a_c"><a class="gsc_a_ac">1</a></td>
          <td class="gsc_a_y"><span class="gsc_a_h">2024</span></td>
        </tr>
      </tbody></table>
      <button id="gsc_bpf_more" disabled>Show more</button>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body=html,
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.has_show_more_button is False


def test_parse_profile_page_regression_fixture_profile_p1rwlvo() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=P1RwlvoAAAAJ",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=P1RwlvoAAAAJ",
        body=_regression_fixture("profile_P1RwlvoAAAAJ.html"),
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.state_reason == "publications_extracted"
    assert parsed.profile_name == "WENRUI ZUO"
    assert len(parsed.publications) == 5
    assert parsed.has_show_more_button is False
    assert parsed.articles_range in {"Articles 1-5", "Articles 1–5"}
    assert "possible_partial_page_show_more_present" not in parsed.warnings
    assert all(item.cluster_id for item in parsed.publications)


def test_parse_profile_page_regression_fixture_profile_lz5d() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=LZ5D_p4AAAAJ",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=LZ5D_p4AAAAJ",
        body=_regression_fixture("profile_LZ5D_p4AAAAJ.html"),
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.state_reason == "publications_extracted"
    assert parsed.profile_name == "Doaa Elmatary"
    assert len(parsed.publications) == 12
    assert parsed.has_show_more_button is False
    assert parsed.articles_range in {"Articles 1-12", "Articles 1–12"}
    assert "possible_partial_page_show_more_present" not in parsed.warnings
    assert any(item.venue_text is None for item in parsed.publications)


def test_parse_profile_page_regression_fixture_blocked_redirect() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=AAAAAAAAAAAA",
        status_code=200,
        final_url=(
            "https://accounts.google.com/v3/signin/identifier"
            "?continue=https%3A%2F%2Fscholar.google.com%2Fcitations%3Fhl%3Den%26user%3DAAAAAAAAAAAA"
        ),
        body=_regression_fixture("profile_AAAAAAAAAAAA.html"),
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.BLOCKED_OR_CAPTCHA
    assert parsed.state_reason == "blocked_accounts_redirect"
    assert parsed.profile_name is None
    assert len(parsed.publications) == 0


def test_parse_author_search_page_extracts_candidates_with_image() -> None:
    html = """
    <html>
      <body>
        <div class="gsc_1usr">
          <img src="/citations/images/avatar_scholar_256.png" />
          <a class="gs_ai_name" href="/citations?hl=en&user=abcDEF123456">Ada Lovelace</a>
          <div class="gs_ai_aff">Analytical Engine Lab</div>
          <div class="gs_ai_eml">Verified email at computing.example</div>
          <div class="gs_ai_cby">Cited by 128</div>
          <a class="gs_ai_one_int">Algorithms</a>
          <a class="gs_ai_one_int">Mathematics</a>
        </div>
      </body>
    </html>
    """
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        body=html,
        error=None,
    )

    parsed = parse_author_search_page(fetch_result)

    assert parsed.state == ParseState.OK
    assert parsed.state_reason == "author_candidates_extracted"
    assert len(parsed.candidates) == 1

    candidate = parsed.candidates[0]
    assert candidate.scholar_id == "abcDEF123456"
    assert candidate.display_name == "Ada Lovelace"
    assert candidate.affiliation == "Analytical Engine Lab"
    assert candidate.email_domain == "computing.example"
    assert candidate.cited_by_count == 128
    assert candidate.interests == ["Algorithms", "Mathematics"]
    assert candidate.profile_url.startswith("https://scholar.google.com/citations")
    assert candidate.profile_image_url == "https://scholar.google.com/citations/images/avatar_scholar_256.png"


def test_parse_author_search_page_detects_no_results_keyword() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=nope",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=nope",
        body="<html><body>Your search didn't match any user profiles.</body></html>",
        error=None,
    )

    parsed = parse_author_search_page(fetch_result)

    assert parsed.state == ParseState.NO_RESULTS
    assert parsed.state_reason == "no_results_keyword_detected"
    assert len(parsed.candidates) == 0


def test_parse_author_search_page_classifies_http_429_as_blocked() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        status_code=429,
        final_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        body="<html><body>Too many requests</body></html>",
        error=None,
    )

    parsed = parse_author_search_page(fetch_result)

    assert parsed.state == ParseState.BLOCKED_OR_CAPTCHA
    assert parsed.state_reason == "blocked_http_429_rate_limited"
