from __future__ import annotations

from urllib.parse import urlparse

from app.services.domains.scholars.constants import MAX_IMAGE_URL_LENGTH, SCHOLAR_ID_PATTERN
from app.services.domains.scholars.exceptions import ScholarServiceError


def validate_scholar_id(value: str) -> str:
    scholar_id = value.strip()
    if not SCHOLAR_ID_PATTERN.fullmatch(scholar_id):
        raise ScholarServiceError("Scholar ID must match [a-zA-Z0-9_-]{12}.")
    return scholar_id


def normalize_display_name(value: str) -> str | None:
    normalized = value.strip()
    return normalized if normalized else None


def normalize_profile_image_url(value: str | None) -> str | None:
    if value is None:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if len(candidate) > MAX_IMAGE_URL_LENGTH:
        raise ScholarServiceError(
            f"Image URL must be {MAX_IMAGE_URL_LENGTH} characters or fewer."
        )

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ScholarServiceError("Image URL must be an absolute http(s) URL.")

    return candidate
