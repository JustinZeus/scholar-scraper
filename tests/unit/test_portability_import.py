from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.portability.publication_import import (
    _build_imported_publication_input,
    _initialize_import_counters,
    _update_link_counters,
)


def _mock_profile(scholar_id: str = "ABC123DEF456") -> Any:
    profile = MagicMock()
    profile.id = 1
    profile.scholar_id = scholar_id
    return profile


def _scholar_map(scholar_id: str = "ABC123DEF456") -> dict[str, Any]:
    return {scholar_id: _mock_profile(scholar_id)}


class TestBuildImportedPublicationInput:
    def test_returns_parsed_input_for_valid_item(self) -> None:
        item = {
            "scholar_id": "ABC123DEF456",
            "title": "Deep Learning",
            "year": 2024,
            "author_text": "Smith, J",
            "venue_text": "ICML",
            "citation_count": 10,
        }
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert result.title == "Deep Learning"
        assert result.year == 2024
        assert result.citation_count == 10
        assert result.author_text == "Smith, J"

    def test_returns_none_when_title_missing(self) -> None:
        item = {"scholar_id": "ABC123DEF456"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is None

    def test_returns_none_when_scholar_id_missing(self) -> None:
        item = {"title": "Test Title"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is None

    def test_returns_none_when_scholar_not_in_map(self) -> None:
        item = {"scholar_id": "UNKNOWN12345", "title": "Test Title"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is None

    def test_defaults_is_read_to_false(self) -> None:
        item = {"scholar_id": "ABC123DEF456", "title": "Test Title"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert result.is_read is False

    def test_respects_is_read_true(self) -> None:
        item = {"scholar_id": "ABC123DEF456", "title": "Test Title", "is_read": True}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert result.is_read is True

    def test_normalizes_year(self) -> None:
        item = {"scholar_id": "ABC123DEF456", "title": "Test Title", "year": "invalid"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert result.year is None

    def test_normalizes_citation_count(self) -> None:
        item = {"scholar_id": "ABC123DEF456", "title": "Test Title", "citation_count": "not_a_number"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert result.citation_count == 0

    def test_computes_fingerprint_when_not_provided(self) -> None:
        item = {"scholar_id": "ABC123DEF456", "title": "Test Title"}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert len(result.fingerprint) == 64

    def test_uses_provided_valid_fingerprint(self) -> None:
        valid_sha = "b" * 64
        item = {"scholar_id": "ABC123DEF456", "title": "Test Title", "fingerprint_sha256": valid_sha}
        result = _build_imported_publication_input(item=item, scholar_map=_scholar_map())
        assert result is not None
        assert result.fingerprint == valid_sha


class TestInitializeImportCounters:
    def test_adds_publication_and_link_keys(self) -> None:
        counters: dict[str, int] = {"existing_key": 5}
        _initialize_import_counters(counters)
        assert counters["publications_created"] == 0
        assert counters["publications_updated"] == 0
        assert counters["links_created"] == 0
        assert counters["links_updated"] == 0
        assert counters["existing_key"] == 5


class TestUpdateLinkCounters:
    def test_increments_created(self) -> None:
        counters = {"links_created": 0, "links_updated": 0}
        _update_link_counters(counters=counters, link_created=True, link_updated=False)
        assert counters["links_created"] == 1
        assert counters["links_updated"] == 0

    def test_increments_updated(self) -> None:
        counters = {"links_created": 0, "links_updated": 0}
        _update_link_counters(counters=counters, link_created=False, link_updated=True)
        assert counters["links_created"] == 0
        assert counters["links_updated"] == 1

    def test_no_change_when_both_false(self) -> None:
        counters = {"links_created": 0, "links_updated": 0}
        _update_link_counters(counters=counters, link_created=False, link_updated=False)
        assert counters["links_created"] == 0
        assert counters["links_updated"] == 0
