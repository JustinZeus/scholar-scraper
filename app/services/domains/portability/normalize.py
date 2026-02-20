from __future__ import annotations

import hashlib
from typing import Any

from app.services.domains.ingestion.application import normalize_title
from app.services.domains.portability.constants import (
    MAX_IMPORT_PUBLICATIONS,
    MAX_IMPORT_SCHOLARS,
    SHA256_RE,
    WORD_RE,
)
from app.services.domains.portability.types import ImportExportError


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_optional_year(value: Any) -> int | None:
    if value is None:
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if year < 1500 or year > 3000:
        return None
    return year


def _normalize_citation_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _first_author_last_name(authors_text: str | None) -> str:
    if not authors_text:
        return ""
    first_author = authors_text.split(",", maxsplit=1)[0].strip().lower()
    words = WORD_RE.findall(first_author)
    if not words:
        return ""
    return words[-1]


def _first_venue_word(venue_text: str | None) -> str:
    if not venue_text:
        return ""
    words = WORD_RE.findall(venue_text.lower())
    if not words:
        return ""
    return words[0]


def _build_fingerprint(
    *,
    title: str,
    year: int | None,
    author_text: str | None,
    venue_text: str | None,
) -> str:
    canonical = "|".join(
        [
            normalize_title(title),
            str(year) if year is not None else "",
            _first_author_last_name(author_text),
            _first_venue_word(venue_text),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_fingerprint(
    *,
    title: str,
    year: int | None,
    author_text: str | None,
    venue_text: str | None,
    provided_fingerprint: Any,
) -> str:
    normalized = _normalize_optional_text(provided_fingerprint)
    if normalized and SHA256_RE.fullmatch(normalized.lower()):
        return normalized.lower()
    return _build_fingerprint(
        title=title,
        year=year,
        author_text=author_text,
        venue_text=venue_text,
    )


def _validate_import_sizes(
    *,
    scholars: list[dict[str, Any]],
    publications: list[dict[str, Any]],
) -> None:
    if len(scholars) > MAX_IMPORT_SCHOLARS:
        raise ImportExportError(f"Import exceeds max scholars ({MAX_IMPORT_SCHOLARS}).")
    if len(publications) > MAX_IMPORT_PUBLICATIONS:
        raise ImportExportError(
            f"Import exceeds max publications ({MAX_IMPORT_PUBLICATIONS})."
        )
