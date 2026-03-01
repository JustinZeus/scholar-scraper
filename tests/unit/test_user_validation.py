from __future__ import annotations

import pytest

from app.services.users.application import (
    UserServiceError,
    normalize_email,
    validate_email,
    validate_password,
)


class TestNormalizeEmail:
    def test_lowercases_and_strips(self) -> None:
        assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"

    def test_already_normalized(self) -> None:
        assert normalize_email("user@example.com") == "user@example.com"


class TestValidateEmail:
    def test_valid_email(self) -> None:
        assert validate_email("user@example.com") == "user@example.com"

    def test_strips_and_lowercases(self) -> None:
        assert validate_email("  User@Example.COM  ") == "user@example.com"

    def test_rejects_missing_at(self) -> None:
        with pytest.raises(UserServiceError, match="valid email"):
            validate_email("userexample.com")

    def test_rejects_missing_domain(self) -> None:
        with pytest.raises(UserServiceError, match="valid email"):
            validate_email("user@")

    def test_rejects_missing_tld(self) -> None:
        with pytest.raises(UserServiceError, match="valid email"):
            validate_email("user@example")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(UserServiceError, match="valid email"):
            validate_email("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(UserServiceError, match="valid email"):
            validate_email("   ")

    def test_rejects_spaces_in_local_part(self) -> None:
        with pytest.raises(UserServiceError, match="valid email"):
            validate_email("us er@example.com")

    def test_accepts_plus_addressing(self) -> None:
        assert validate_email("user+tag@example.com") == "user+tag@example.com"

    def test_accepts_dots_in_local(self) -> None:
        assert validate_email("first.last@example.com") == "first.last@example.com"


class TestValidatePassword:
    def test_valid_password(self) -> None:
        assert validate_password("securepass") == "securepass"

    def test_exactly_8_characters(self) -> None:
        assert validate_password("12345678") == "12345678"

    def test_rejects_7_characters(self) -> None:
        with pytest.raises(UserServiceError, match="at least 8"):
            validate_password("1234567")

    def test_rejects_empty(self) -> None:
        with pytest.raises(UserServiceError, match="at least 8"):
            validate_password("")

    def test_strips_whitespace(self) -> None:
        assert validate_password("  securepass  ") == "securepass"

    def test_whitespace_only_too_short(self) -> None:
        with pytest.raises(UserServiceError, match="at least 8"):
            validate_password("       ")
