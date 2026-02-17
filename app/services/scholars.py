from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScholarProfile
from app.services.scholar_parser import (
    ParseState,
    ParsedAuthorSearchPage,
    parse_author_search_page,
    parse_profile_page,
)
from app.services.scholar_source import ScholarSource

SCHOLAR_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{12}$")
MAX_IMAGE_URL_LENGTH = 2048
MAX_AUTHOR_SEARCH_LIMIT = 25
DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES = 512
DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS = 300
DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD = 1
DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS = 1800
DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS = 3.0
DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS = 1.0
ALLOWED_IMAGE_UPLOAD_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
SEARCH_DISABLED_REASON = "search_disabled_by_configuration"
SEARCH_COOLDOWN_REASON = "search_temporarily_disabled_due_to_repeated_blocks"
SEARCH_CACHED_BLOCK_REASON = "search_temporarily_disabled_from_cached_blocked_response"

STATE_REASON_HINTS: dict[str, str] = {
    SEARCH_DISABLED_REASON: (
        "Scholar name search is currently disabled by service policy. "
        "Add scholars by profile URL or Scholar ID."
    ),
    SEARCH_COOLDOWN_REASON: (
        "Scholar name search is temporarily paused after repeated block responses. "
        "Use Scholar URL/ID adds until cooldown expires."
    ),
    SEARCH_CACHED_BLOCK_REASON: (
        "A recent blocked response was cached to reduce traffic. "
        "Retry later or add by Scholar URL/ID."
    ),
    "network_dns_resolution_failed": (
        "DNS resolution failed while reaching scholar.google.com. "
        "Verify container DNS/network and retry."
    ),
    "network_timeout": (
        "Request timed out before Google Scholar responded. "
        "Increase delay/backoff and retry."
    ),
    "network_tls_error": (
        "TLS handshake/certificate validation failed. "
        "Verify outbound TLS/network configuration."
    ),
    "blocked_http_429_rate_limited": (
        "Google Scholar rate-limited the request. "
        "Slow request cadence and retry later."
    ),
    "blocked_unusual_traffic_detected": (
        "Google Scholar flagged traffic as unusual. "
        "Increase delay/jitter and reduce concurrent scraping."
    ),
    "blocked_accounts_redirect": (
        "Request was redirected to Google Account sign-in. "
        "Treat as access block and retry later."
    ),
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AuthorSearchCacheEntry:
    parsed: ParsedAuthorSearchPage
    expires_at_monotonic: float
    cached_at_utc: datetime


_AUTHOR_SEARCH_EXECUTION_LOCK = asyncio.Lock()
_AUTHOR_SEARCH_CACHE: OrderedDict[str, _AuthorSearchCacheEntry] = OrderedDict()
_AUTHOR_SEARCH_LAST_LIVE_REQUEST_MONOTONIC = 0.0
_AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC: datetime | None = None
_AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT = 0


class ScholarServiceError(ValueError):
    """Raised for expected scholar-management validation failures."""


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


def _ensure_upload_root(upload_dir: str, *, create: bool) -> Path:
    root = Path(upload_dir).expanduser().resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_upload_path(upload_root: Path, relative_path: str) -> Path:
    candidate = (upload_root / relative_path).resolve()
    if upload_root != candidate and upload_root not in candidate.parents:
        raise ScholarServiceError("Invalid scholar image path.")
    return candidate


def _safe_remove_upload(upload_root: Path, relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        file_path = _resolve_upload_path(upload_root, relative_path)
    except ScholarServiceError:
        return

    try:
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except OSError:
        return


def resolve_profile_image(
    profile: ScholarProfile,
    *,
    uploaded_image_url: str | None,
) -> tuple[str | None, str]:
    if profile.profile_image_upload_path and uploaded_image_url:
        return uploaded_image_url, "upload"
    if profile.profile_image_override_url:
        return profile.profile_image_override_url, "override"
    if profile.profile_image_url:
        return profile.profile_image_url, "scraped"
    return None, "none"


def resolve_upload_file_path(*, upload_dir: str, relative_path: str) -> Path:
    root = _ensure_upload_root(upload_dir, create=False)
    return _resolve_upload_path(root, relative_path)


def scrape_state_hint(*, state: ParseState, state_reason: str) -> str | None:
    if state not in {ParseState.NETWORK_ERROR, ParseState.BLOCKED_OR_CAPTCHA}:
        return None
    return STATE_REASON_HINTS.get(state_reason)


def _merge_warnings(base: list[str], extra: list[str]) -> list[str]:
    if not extra:
        return sorted(set(base))
    return sorted(set(base + extra))


def _trim_author_search_result(
    parsed: ParsedAuthorSearchPage,
    *,
    limit: int,
    extra_warnings: list[str] | None = None,
    state_reason_override: str | None = None,
) -> ParsedAuthorSearchPage:
    return ParsedAuthorSearchPage(
        state=parsed.state,
        state_reason=state_reason_override or parsed.state_reason,
        candidates=parsed.candidates[: max(1, min(int(limit), MAX_AUTHOR_SEARCH_LIMIT))],
        marker_counts=parsed.marker_counts,
        warnings=_merge_warnings(parsed.warnings, extra_warnings or []),
    )


def _policy_blocked_author_search_result(
    *,
    reason: str,
    warning_codes: list[str],
    limit: int,
) -> ParsedAuthorSearchPage:
    _ = limit
    return ParsedAuthorSearchPage(
        state=ParseState.BLOCKED_OR_CAPTCHA,
        state_reason=reason,
        candidates=[],
        marker_counts={},
        warnings=_merge_warnings([], warning_codes),
    )


def _cache_get_author_search_result(query_key: str, now_monotonic: float) -> _AuthorSearchCacheEntry | None:
    entry = _AUTHOR_SEARCH_CACHE.get(query_key)
    if entry is None:
        return None
    if entry.expires_at_monotonic <= now_monotonic:
        _AUTHOR_SEARCH_CACHE.pop(query_key, None)
        return None
    _AUTHOR_SEARCH_CACHE.move_to_end(query_key)
    return entry


def _cache_set_author_search_result(
    *,
    query_key: str,
    parsed: ParsedAuthorSearchPage,
    ttl_seconds: float,
    max_entries: int,
) -> None:
    ttl = max(float(ttl_seconds), 0.0)
    if ttl <= 0.0:
        _AUTHOR_SEARCH_CACHE.pop(query_key, None)
        return

    _AUTHOR_SEARCH_CACHE[query_key] = _AuthorSearchCacheEntry(
        parsed=parsed,
        expires_at_monotonic=time.monotonic() + ttl,
        cached_at_utc=datetime.now(timezone.utc),
    )
    _AUTHOR_SEARCH_CACHE.move_to_end(query_key)

    bounded_max_entries = max(1, int(max_entries))
    while len(_AUTHOR_SEARCH_CACHE) > bounded_max_entries:
        _AUTHOR_SEARCH_CACHE.popitem(last=False)


def _is_author_search_block_state(parsed: ParsedAuthorSearchPage) -> bool:
    return parsed.state == ParseState.BLOCKED_OR_CAPTCHA


def _author_search_cooldown_remaining_seconds(now_utc: datetime) -> int:
    if _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC is None:
        return 0
    remaining_seconds = int((_AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC - now_utc).total_seconds())
    return max(0, remaining_seconds)


def _reset_author_search_runtime_state_for_tests() -> None:
    global _AUTHOR_SEARCH_LAST_LIVE_REQUEST_MONOTONIC
    global _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC
    global _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT
    _AUTHOR_SEARCH_CACHE.clear()
    _AUTHOR_SEARCH_LAST_LIVE_REQUEST_MONOTONIC = 0.0
    _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC = None
    _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT = 0


async def list_scholars_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> list[ScholarProfile]:
    result = await db_session.execute(
        select(ScholarProfile)
        .where(ScholarProfile.user_id == user_id)
        .order_by(ScholarProfile.created_at.desc(), ScholarProfile.id.desc())
    )
    return list(result.scalars().all())


async def create_scholar_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_id: str,
    display_name: str,
    profile_image_url: str | None = None,
) -> ScholarProfile:
    profile = ScholarProfile(
        user_id=user_id,
        scholar_id=validate_scholar_id(scholar_id),
        display_name=normalize_display_name(display_name),
        profile_image_url=normalize_profile_image_url(profile_image_url),
    )
    db_session.add(profile)
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise ScholarServiceError("That scholar is already tracked for this account.") from exc
    await db_session.refresh(profile)
    return profile


async def get_user_scholar_by_id(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
) -> ScholarProfile | None:
    result = await db_session.execute(
        select(ScholarProfile).where(
            ScholarProfile.id == scholar_profile_id,
            ScholarProfile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def toggle_scholar_enabled(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
) -> ScholarProfile:
    profile.is_enabled = not profile.is_enabled
    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def delete_scholar(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    upload_dir: str | None = None,
) -> None:
    if upload_dir:
        upload_root = _ensure_upload_root(upload_dir, create=True)
        _safe_remove_upload(upload_root, profile.profile_image_upload_path)

    await db_session.delete(profile)
    await db_session.commit()


async def search_author_candidates(
    *,
    source: ScholarSource,
    query: str,
    limit: int,
    network_error_retries: int = 1,
    retry_backoff_seconds: float = 1.0,
    search_enabled: bool = True,
    cache_ttl_seconds: int = 21_600,
    blocked_cache_ttl_seconds: int = DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS,
    cache_max_entries: int = DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES,
    min_interval_seconds: float = DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS,
    interval_jitter_seconds: float = DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS,
    cooldown_block_threshold: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD,
    cooldown_seconds: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS,
) -> ParsedAuthorSearchPage:
    global _AUTHOR_SEARCH_LAST_LIVE_REQUEST_MONOTONIC
    global _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC
    global _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT

    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise ScholarServiceError("Search query must be at least 2 characters.")
    bounded_limit = max(1, min(int(limit), MAX_AUTHOR_SEARCH_LIMIT))
    query_key = normalized_query.casefold()

    if not search_enabled:
        logger.warning(
            "scholar_search.disabled_by_configuration",
            extra={
                "event": "scholar_search.disabled_by_configuration",
                "query": normalized_query,
            },
        )
        return _policy_blocked_author_search_result(
            reason=SEARCH_DISABLED_REASON,
            warning_codes=["author_search_disabled_by_configuration"],
            limit=bounded_limit,
        )

    async with _AUTHOR_SEARCH_EXECUTION_LOCK:
        now_utc = datetime.now(timezone.utc)
        now_monotonic = time.monotonic()

        cooldown_remaining_seconds = _author_search_cooldown_remaining_seconds(now_utc)
        if cooldown_remaining_seconds > 0:
            logger.warning(
                "scholar_search.cooldown_active",
                extra={
                    "event": "scholar_search.cooldown_active",
                    "query": normalized_query,
                    "cooldown_remaining_seconds": cooldown_remaining_seconds,
                    "cooldown_until_utc": _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC.isoformat()
                    if _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC
                    else None,
                },
            )
            return _policy_blocked_author_search_result(
                reason=SEARCH_COOLDOWN_REASON,
                warning_codes=[
                    "author_search_cooldown_active",
                    f"author_search_cooldown_remaining_{cooldown_remaining_seconds}s",
                ],
                limit=bounded_limit,
            )

        cached_entry = _cache_get_author_search_result(query_key, now_monotonic)
        if cached_entry is not None:
            cached = cached_entry.parsed
            state_reason_override = (
                SEARCH_CACHED_BLOCK_REASON if _is_author_search_block_state(cached) else None
            )
            logger.info(
                "scholar_search.cache_hit",
                extra={
                    "event": "scholar_search.cache_hit",
                    "query": normalized_query,
                    "state": cached.state.value,
                    "state_reason": cached.state_reason,
                },
            )
            return _trim_author_search_result(
                cached,
                limit=bounded_limit,
                extra_warnings=["author_search_served_from_cache"],
                state_reason_override=state_reason_override,
            )

        enforced_wait_seconds = (
            (_AUTHOR_SEARCH_LAST_LIVE_REQUEST_MONOTONIC + max(float(min_interval_seconds), 0.0))
            - now_monotonic
        )
        jitter_seconds = random.uniform(0.0, max(float(interval_jitter_seconds), 0.0))
        sleep_seconds = max(0.0, enforced_wait_seconds) + jitter_seconds
        if sleep_seconds > 0.0:
            logger.info(
                "scholar_search.throttle_wait",
                extra={
                    "event": "scholar_search.throttle_wait",
                    "query": normalized_query,
                    "sleep_seconds": round(sleep_seconds, 3),
                },
            )
            await asyncio.sleep(sleep_seconds)

        max_attempts = max(1, int(network_error_retries) + 1)
        parsed: ParsedAuthorSearchPage | None = None
        retry_warnings: list[str] = []

        for attempt_index in range(max_attempts):
            fetch_result = await source.fetch_author_search_html(normalized_query, start=0)
            parsed = parse_author_search_page(fetch_result)
            if parsed.state != ParseState.NETWORK_ERROR or attempt_index >= max_attempts - 1:
                break

            retry_warnings.append("network_retry_scheduled_for_author_search")
            sleep_seconds = max(float(retry_backoff_seconds), 0.0) * (2**attempt_index)
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

        _AUTHOR_SEARCH_LAST_LIVE_REQUEST_MONOTONIC = time.monotonic()

        if parsed is None:
            raise ScholarServiceError("Unable to complete scholar author search.")

        merged_parsed = replace(
            parsed,
            warnings=_merge_warnings(parsed.warnings, retry_warnings),
        )

        if _is_author_search_block_state(merged_parsed):
            _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT += 1
            logger.warning(
                "scholar_search.block_detected",
                extra={
                    "event": "scholar_search.block_detected",
                    "query": normalized_query,
                    "state_reason": merged_parsed.state_reason,
                    "consecutive_blocked_count": _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT,
                },
            )
            if _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT >= max(1, int(cooldown_block_threshold)):
                _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC = datetime.now(timezone.utc) + timedelta(
                    seconds=max(60, int(cooldown_seconds))
                )
                _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT = 0
                merged_parsed = replace(
                    merged_parsed,
                    warnings=_merge_warnings(
                        merged_parsed.warnings,
                        ["author_search_circuit_breaker_armed"],
                    ),
                )
                logger.error(
                    "scholar_search.cooldown_activated",
                    extra={
                        "event": "scholar_search.cooldown_activated",
                        "query": normalized_query,
                        "cooldown_until_utc": _AUTHOR_SEARCH_COOLDOWN_UNTIL_UTC.isoformat(),
                    },
                )
        else:
            _AUTHOR_SEARCH_CONSECUTIVE_BLOCKED_COUNT = 0

        ttl_seconds = (
            min(max(1, int(blocked_cache_ttl_seconds)), max(1, int(cache_ttl_seconds)))
            if _is_author_search_block_state(merged_parsed)
            else max(1, int(cache_ttl_seconds))
        )
        _cache_set_author_search_result(
            query_key=query_key,
            parsed=merged_parsed,
            ttl_seconds=float(ttl_seconds),
            max_entries=cache_max_entries,
        )

    return _trim_author_search_result(
        merged_parsed,
        limit=bounded_limit,
    )


async def hydrate_profile_metadata(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    source: ScholarSource,
) -> ScholarProfile:
    fetch_result = await source.fetch_profile_html(profile.scholar_id)
    parsed_page = parse_profile_page(fetch_result)

    if parsed_page.profile_name and not (profile.display_name or "").strip():
        profile.display_name = parsed_page.profile_name
    if parsed_page.profile_image_url and not profile.profile_image_url:
        profile.profile_image_url = parsed_page.profile_image_url

    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def set_profile_image_override_url(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    image_url: str | None,
    upload_dir: str,
) -> ScholarProfile:
    upload_root = _ensure_upload_root(upload_dir, create=True)
    _safe_remove_upload(upload_root, profile.profile_image_upload_path)

    profile.profile_image_upload_path = None
    profile.profile_image_override_url = normalize_profile_image_url(image_url)

    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def clear_profile_image_customization(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    upload_dir: str,
) -> ScholarProfile:
    upload_root = _ensure_upload_root(upload_dir, create=True)
    _safe_remove_upload(upload_root, profile.profile_image_upload_path)

    profile.profile_image_upload_path = None
    profile.profile_image_override_url = None

    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def set_profile_image_upload(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    content_type: str | None,
    image_bytes: bytes,
    upload_dir: str,
    max_upload_bytes: int,
) -> ScholarProfile:
    normalized_content_type = (content_type or "").strip().lower()
    extension = ALLOWED_IMAGE_UPLOAD_CONTENT_TYPES.get(normalized_content_type)
    if extension is None:
        raise ScholarServiceError(
            "Unsupported image type. Use JPEG, PNG, WEBP, or GIF."
        )

    if not image_bytes:
        raise ScholarServiceError("Uploaded image file is empty.")

    if len(image_bytes) > max_upload_bytes:
        raise ScholarServiceError(
            f"Uploaded image exceeds {max_upload_bytes} bytes."
        )

    upload_root = _ensure_upload_root(upload_dir, create=True)
    user_dir = upload_root / str(profile.user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{profile.id}_{uuid4().hex}{extension}"
    relative_path = os.path.join(str(profile.user_id), filename)
    absolute_path = _resolve_upload_path(upload_root, relative_path)
    absolute_path.write_bytes(image_bytes)

    old_path = profile.profile_image_upload_path
    profile.profile_image_upload_path = relative_path
    profile.profile_image_override_url = None

    await db_session.commit()
    await db_session.refresh(profile)

    if old_path and old_path != relative_path:
        _safe_remove_upload(upload_root, old_path)

    return profile
