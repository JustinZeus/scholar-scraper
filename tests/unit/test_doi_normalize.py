from __future__ import annotations

from app.services.domains.doi.normalize import first_doi_from_texts, normalize_doi


def test_normalize_doi_extracts_and_lowercases() -> None:
    value = "https://doi.org/10.48550/ARXIV.1412.6980"
    assert normalize_doi(value) == "10.48550/arxiv.1412.6980"


def test_first_doi_from_texts_prefers_first_match() -> None:
    result = first_doi_from_texts(
        "no doi here",
        "venue text 10.1000/ABC-123",
        "title with 10.9999/ignored",
    )
    assert result == "10.1000/abc-123"
