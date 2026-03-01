from __future__ import annotations

import os
import tempfile

import pytest

from app.services.scholars.constants import MAX_IMAGE_URL_LENGTH
from app.services.scholars.exceptions import ScholarServiceError
from app.services.scholars.uploads import (
    _ensure_upload_root,
    _resolve_upload_path,
    _safe_remove_upload,
    resolve_upload_file_path,
)
from app.services.scholars.validators import (
    normalize_display_name,
    normalize_profile_image_url,
    validate_scholar_id,
)


class TestValidateScholarId:
    def test_valid_12_char_id(self) -> None:
        assert validate_scholar_id("ABCDEF123456") == "ABCDEF123456"

    def test_valid_with_hyphens_and_underscores(self) -> None:
        assert validate_scholar_id("AB-CD_EF1234") == "AB-CD_EF1234"

    def test_strips_whitespace(self) -> None:
        assert validate_scholar_id("  ABCDEF123456  ") == "ABCDEF123456"

    def test_rejects_too_short(self) -> None:
        with pytest.raises(ScholarServiceError, match="12"):
            validate_scholar_id("ABC123")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ScholarServiceError, match="12"):
            validate_scholar_id("ABCDEF1234567")

    def test_rejects_special_characters(self) -> None:
        with pytest.raises(ScholarServiceError, match="12"):
            validate_scholar_id("ABCDEF12345!")


class TestNormalizeDisplayName:
    def test_returns_stripped_name(self) -> None:
        assert normalize_display_name("  John Doe  ") == "John Doe"

    def test_returns_none_for_empty(self) -> None:
        assert normalize_display_name("") is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert normalize_display_name("   ") is None

    def test_preserves_non_empty(self) -> None:
        assert normalize_display_name("A") == "A"


class TestNormalizeProfileImageUrl:
    def test_valid_https_url(self) -> None:
        assert normalize_profile_image_url("https://example.com/img.png") == "https://example.com/img.png"

    def test_valid_http_url(self) -> None:
        assert normalize_profile_image_url("http://example.com/img.png") == "http://example.com/img.png"

    def test_returns_none_for_none(self) -> None:
        assert normalize_profile_image_url(None) is None

    def test_returns_none_for_empty(self) -> None:
        assert normalize_profile_image_url("") is None

    def test_returns_none_for_whitespace(self) -> None:
        assert normalize_profile_image_url("   ") is None

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ScholarServiceError, match="http"):
            normalize_profile_image_url("ftp://example.com/img.png")

    def test_rejects_no_scheme(self) -> None:
        with pytest.raises(ScholarServiceError, match="http"):
            normalize_profile_image_url("example.com/img.png")

    def test_rejects_url_too_long(self) -> None:
        long_url = "https://example.com/" + "a" * MAX_IMAGE_URL_LENGTH
        with pytest.raises(ScholarServiceError, match="characters or fewer"):
            normalize_profile_image_url(long_url)

    def test_accepts_url_at_max_length(self) -> None:
        url = "https://example.com/" + "a" * (MAX_IMAGE_URL_LENGTH - len("https://example.com/"))
        assert len(url) == MAX_IMAGE_URL_LENGTH
        assert normalize_profile_image_url(url) == url


class TestUploadPathSafety:
    def test_resolve_upload_path_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _ensure_upload_root(tmpdir, create=False)
            with pytest.raises(ScholarServiceError, match="Invalid"):
                _resolve_upload_path(root, "../../../etc/passwd")

    def test_resolve_upload_path_accepts_valid_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _ensure_upload_root(tmpdir, create=False)
            result = _resolve_upload_path(root, "scholar_img.png")
            assert result.name == "scholar_img.png"
            assert root in result.parents or root == result.parent

    def test_ensure_upload_root_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "uploads", "images")
            root = _ensure_upload_root(new_dir, create=True)
            assert root.exists()

    def test_safe_remove_upload_removes_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _ensure_upload_root(tmpdir, create=False)
            test_file = root / "test.png"
            test_file.write_bytes(b"fake image")
            assert test_file.exists()
            _safe_remove_upload(root, "test.png")
            assert not test_file.exists()

    def test_safe_remove_upload_ignores_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _ensure_upload_root(tmpdir, create=False)
            _safe_remove_upload(root, "nonexistent.png")

    def test_safe_remove_upload_ignores_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _ensure_upload_root(tmpdir, create=False)
            _safe_remove_upload(root, None)

    def test_safe_remove_upload_ignores_traversal_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _ensure_upload_root(tmpdir, create=False)
            _safe_remove_upload(root, "../../../etc/passwd")

    def test_resolve_upload_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_upload_file_path(upload_dir=tmpdir, relative_path="img.png")
            assert result.name == "img.png"
