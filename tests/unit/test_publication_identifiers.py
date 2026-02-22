from __future__ import annotations

from app.services.domains.publication_identifiers import application as identifier_service


def test_derive_display_identifier_prefers_doi_over_arxiv() -> None:
    display = identifier_service.derive_display_identifier_from_values(
        doi="10.1000/example",
        pub_url="https://arxiv.org/abs/1504.08025",
        pdf_url=None,
    )
    assert display is not None
    assert display.kind == "doi"
    assert display.value == "10.1000/example"
    assert display.url == "https://doi.org/10.1000/example"


def test_derive_display_identifier_uses_arxiv_when_doi_missing() -> None:
    display = identifier_service.derive_display_identifier_from_values(
        doi=None,
        pub_url="https://arxiv.org/pdf/1504.08025v2",
        pdf_url=None,
    )
    assert display is not None
    assert display.kind == "arxiv"
    assert display.value == "1504.08025v2"
    assert display.label == "arXiv: 1504.08025v2"


def test_derive_display_identifier_uses_pmcid_when_present() -> None:
    display = identifier_service.derive_display_identifier_from_values(
        doi=None,
        pub_url=None,
        pdf_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC2175868/pdf/file.pdf",
    )
    assert display is not None
    assert display.kind == "pmcid"
    assert display.value == "PMC2175868"
