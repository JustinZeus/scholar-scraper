from __future__ import annotations

import pytest

from app.services.portability.constants import MAX_IMPORT_PUBLICATIONS, MAX_IMPORT_SCHOLARS
from app.services.portability.normalize import (
    _build_fingerprint,
    _first_author_last_name,
    _first_venue_word,
    _normalize_citation_count,
    _normalize_optional_text,
    _normalize_optional_year,
    _resolve_fingerprint,
    _validate_import_sizes,
)
from app.services.portability.types import ImportExportError


class TestNormalizeOptionalText:
    def test_returns_stripped_string(self) -> None:
        assert _normalize_optional_text("  hello  ") == "hello"

    def test_returns_none_for_none(self) -> None:
        assert _normalize_optional_text(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _normalize_optional_text("") is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert _normalize_optional_text("   ") is None

    def test_coerces_non_string_to_string(self) -> None:
        assert _normalize_optional_text(42) == "42"


class TestNormalizeOptionalYear:
    def test_valid_year(self) -> None:
        assert _normalize_optional_year(2024) == 2024

    def test_string_year(self) -> None:
        assert _normalize_optional_year("1999") == 1999

    def test_returns_none_for_none(self) -> None:
        assert _normalize_optional_year(None) is None

    def test_returns_none_for_non_numeric(self) -> None:
        assert _normalize_optional_year("abc") is None

    def test_returns_none_for_year_below_1500(self) -> None:
        assert _normalize_optional_year(1499) is None

    def test_returns_none_for_year_above_3000(self) -> None:
        assert _normalize_optional_year(3001) is None

    def test_boundary_1500_accepted(self) -> None:
        assert _normalize_optional_year(1500) == 1500

    def test_boundary_3000_accepted(self) -> None:
        assert _normalize_optional_year(3000) == 3000


class TestNormalizeCitationCount:
    def test_valid_positive(self) -> None:
        assert _normalize_citation_count(10) == 10

    def test_zero(self) -> None:
        assert _normalize_citation_count(0) == 0

    def test_negative_clamped_to_zero(self) -> None:
        assert _normalize_citation_count(-5) == 0

    def test_string_number(self) -> None:
        assert _normalize_citation_count("42") == 42

    def test_none_returns_zero(self) -> None:
        assert _normalize_citation_count(None) == 0

    def test_invalid_string_returns_zero(self) -> None:
        assert _normalize_citation_count("abc") == 0


class TestFirstAuthorLastName:
    def test_single_author(self) -> None:
        assert _first_author_last_name("John Smith") == "smith"

    def test_multiple_authors(self) -> None:
        assert _first_author_last_name("Jane Doe, John Smith") == "doe"

    def test_empty_string(self) -> None:
        assert _first_author_last_name("") == ""

    def test_none(self) -> None:
        assert _first_author_last_name(None) == ""


class TestFirstVenueWord:
    def test_returns_first_word(self) -> None:
        assert _first_venue_word("Nature Communications") == "nature"

    def test_empty_string(self) -> None:
        assert _first_venue_word("") == ""

    def test_none(self) -> None:
        assert _first_venue_word(None) == ""


class TestBuildFingerprint:
    def test_produces_64_hex_digest(self) -> None:
        fp = _build_fingerprint(title="Test Title", year=2024, author_text="Smith", venue_text="ICML")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic(self) -> None:
        kwargs = {"title": "Test Title", "year": 2024, "author_text": "Smith", "venue_text": "ICML"}
        assert _build_fingerprint(**kwargs) == _build_fingerprint(**kwargs)

    def test_different_titles_produce_different_fingerprints(self) -> None:
        fp1 = _build_fingerprint(title="Title A", year=2024, author_text=None, venue_text=None)
        fp2 = _build_fingerprint(title="Title B", year=2024, author_text=None, venue_text=None)
        assert fp1 != fp2

    def test_none_year_handled(self) -> None:
        fp = _build_fingerprint(title="Test", year=None, author_text=None, venue_text=None)
        assert len(fp) == 64


class TestResolveFingerprint:
    def test_uses_provided_valid_sha256(self) -> None:
        valid_sha = "a" * 64
        result = _resolve_fingerprint(
            title="Test",
            year=2024,
            author_text=None,
            venue_text=None,
            provided_fingerprint=valid_sha,
        )
        assert result == valid_sha

    def test_computes_fingerprint_when_provided_is_none(self) -> None:
        result = _resolve_fingerprint(
            title="Test",
            year=2024,
            author_text=None,
            venue_text=None,
            provided_fingerprint=None,
        )
        assert len(result) == 64

    def test_computes_fingerprint_when_provided_is_invalid(self) -> None:
        result = _resolve_fingerprint(
            title="Test",
            year=2024,
            author_text=None,
            venue_text=None,
            provided_fingerprint="not-a-sha",
        )
        assert len(result) == 64

    def test_normalizes_provided_to_lowercase(self) -> None:
        valid_sha = "A" * 64
        result = _resolve_fingerprint(
            title="Test",
            year=2024,
            author_text=None,
            venue_text=None,
            provided_fingerprint=valid_sha,
        )
        assert result == "a" * 64


class TestValidateImportSizes:
    def test_accepts_within_limits(self) -> None:
        _validate_import_sizes(scholars=[{}], publications=[{}])

    def test_rejects_too_many_scholars(self) -> None:
        with pytest.raises(ImportExportError, match="max scholars"):
            _validate_import_sizes(
                scholars=[{}] * (MAX_IMPORT_SCHOLARS + 1),
                publications=[],
            )

    def test_rejects_too_many_publications(self) -> None:
        with pytest.raises(ImportExportError, match="max publications"):
            _validate_import_sizes(
                scholars=[],
                publications=[{}] * (MAX_IMPORT_PUBLICATIONS + 1),
            )

    def test_accepts_exact_limit(self) -> None:
        _validate_import_sizes(
            scholars=[{}] * MAX_IMPORT_SCHOLARS,
            publications=[{}] * MAX_IMPORT_PUBLICATIONS,
        )
