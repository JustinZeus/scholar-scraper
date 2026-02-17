from __future__ import annotations

from pathlib import Path

from app.services.scholar_parser import ParseState, parse_profile_page
from app.services.scholar_source import FetchResult


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
    assert publication.year is None
    assert publication.venue_text is None


def test_parse_profile_page_detects_layout_change_when_markers_absent() -> None:
    fetch_result = FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
        body="<html><body><h1>Unexpected page</h1></body></html>",
        error=None,
    )

    parsed = parse_profile_page(fetch_result)

    assert parsed.state == ParseState.LAYOUT_CHANGED
    assert parsed.state_reason == "layout_markers_missing"
    assert "no_rows_detected" in parsed.warnings


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
    assert parsed.state_reason == "network_error_missing_status_code"


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
