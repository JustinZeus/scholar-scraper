from __future__ import annotations

import pytest

from app.services.domains.scholar.parser_types import ScholarDomInvariantError
from app.services.domains.scholar.publication_pdf import (
    extract_link_candidates_from_publication_detail_html,
    is_scholar_publication_detail_url,
)


def test_extract_link_candidates_from_publication_detail_html_reads_gsc_oci_pdf_link() -> None:
    html = """
    <html><body>
      <div id="gsc_oci_title_gg">
        <div class="gsc_oci_title_ggi">
          <a href="https://arxiv.org/pdf/1703.06103" data-clk="x">
            <span class="gsc_vcd_title_ggt">[PDF]</span> from arxiv.org
          </a>
        </div>
      </div>
    </body></html>
    """
    candidates = extract_link_candidates_from_publication_detail_html(html)
    assert candidates.labeled_candidate is not None
    assert candidates.labeled_candidate.url == "https://arxiv.org/pdf/1703.06103"


def test_extract_link_candidates_from_publication_detail_html_returns_no_candidates_when_container_missing() -> None:
    html = "<html><body><div id='gsc_oci_title'>No PDF section</div></body></html>"
    candidates = extract_link_candidates_from_publication_detail_html(html)
    assert candidates.container_seen is False
    assert candidates.labeled_candidate is None
    assert candidates.fallback_candidate is None


def test_extract_pdf_url_from_publication_detail_html_fails_fast_on_malformed_pdf_container() -> None:
    html = """
    <html><body>
      <div id="gsc_oci_title_gg">
        <div class="gsc_oci_title_ggi">
          <a data-clk="x"><span class="gsc_vcd_title_ggt">[PDF]</span> from example.org</a>
        </div>
      </div>
    </body></html>
    """
    with pytest.raises(ScholarDomInvariantError) as exc:
        extract_link_candidates_from_publication_detail_html(html)
    assert exc.value.code == "layout_publication_link_missing_href"


def test_extract_link_candidates_from_publication_detail_html_keeps_unlabeled_fallback() -> None:
    html = """
    <html><body>
      <div id="gsc_oci_title_gg">
        <div class="gsc_oci_title_ggi">
          <a href="https://example.org/download?id=42">from example.org</a>
        </div>
      </div>
    </body></html>
    """
    candidates = extract_link_candidates_from_publication_detail_html(html)
    assert candidates.container_seen is True
    assert candidates.labeled_candidate is None
    assert candidates.fallback_candidate is not None
    assert candidates.fallback_candidate.url == "https://example.org/download?id=42"
    assert candidates.fallback_candidate.label_present is False
    assert "scholar_publication_link_unlabeled_only" in candidates.warnings
    assert candidates.labeled_candidate is None


def test_is_scholar_publication_detail_url_matches_view_citation_links() -> None:
    assert is_scholar_publication_detail_url(
        "https://scholar.google.com/citations?view_op=view_citation&hl=en&user=8200InoAAAAJ&citation_for_view=8200InoAAAAJ:gsN89kCJA0AC"
    ) is True
    assert is_scholar_publication_detail_url("https://example.org/paper") is False
