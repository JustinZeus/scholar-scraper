from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import random
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthorSearchCacheEntry, AuthorSearchRuntimeState, ScholarProfile
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
DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD = 2
DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD = 3
AUTHOR_SEARCH_RUNTIME_STATE_KEY = "global"
AUTHOR_SEARCH_LOCK_NAMESPACE = 3901
AUTHOR_SEARCH_LOCK_KEY = 1
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


async def _acquire_author_search_lock(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
        {
            "namespace": AUTHOR_SEARCH_LOCK_NAMESPACE,
            "lock_key": AUTHOR_SEARCH_LOCK_KEY,
        },
    )


async def _load_runtime_state_for_update(
    db_session: AsyncSession,
) -> AuthorSearchRuntimeState:
    result = await db_session.execute(
        select(AuthorSearchRuntimeState)
        .where(AuthorSearchRuntimeState.state_key == AUTHOR_SEARCH_RUNTIME_STATE_KEY)
        .with_for_update()
    )
    state = result.scalar_one_or_none()
    if state is not None:
        return state

    state = AuthorSearchRuntimeState(state_key=AUTHOR_SEARCH_RUNTIME_STATE_KEY)
    db_session.add(state)
    await db_session.flush()
    return state


def _serialize_parsed_author_search_page(parsed: ParsedAuthorSearchPage) -> dict:
    return {
        "state": parsed.state.value,
        "state_reason": parsed.state_reason,
        "marker_counts": {str(key): int(value) for key, value in parsed.marker_counts.items()},
        "warnings": [str(value) for value in parsed.warnings],
        "candidates": [
            {
                "scholar_id": candidate.scholar_id,
                "display_name": candidate.display_name,
                "affiliation": candidate.affiliation,
                "email_domain": candidate.email_domain,
                "cited_by_count": candidate.cited_by_count,
                "interests": [str(interest) for interest in candidate.interests],
                "profile_url": candidate.profile_url,
                "profile_image_url": candidate.profile_image_url,
            }
            for candidate in parsed.candidates
        ],
    }


def _deserialize_parsed_author_search_page(payload: object) -> ParsedAuthorSearchPage | None:
    if not isinstance(payload, dict):
        return None

    state_raw = str(payload.get("state", "")).strip()
    try:
        state = ParseState(state_raw)
    except ValueError:
        return None

    marker_counts_payload = payload.get("marker_counts")
    marker_counts = (
        {str(key): int(value) for key, value in marker_counts_payload.items()}
        if isinstance(marker_counts_payload, dict)
        else {}
    )
    warnings_payload = payload.get("warnings")
    warnings = (
        [str(value) for value in warnings_payload if isinstance(value, str)]
        if isinstance(warnings_payload, list)
        else []
    )
    from app.services.scholar_parser import ScholarSearchCandidate

    candidates_payload = payload.get("candidates")
    normalized_candidates = []
    for value in candidates_payload if isinstance(candidates_payload, list) else []:
        if not isinstance(value, dict):
            continue
        scholar_id = str(value.get("scholar_id", "")).strip()
        display_name = str(value.get("display_name", "")).strip()
        profile_url = str(value.get("profile_url", "")).strip()
        if not scholar_id or not display_name or not profile_url:
            continue
        interests_payload = value.get("interests")
        interests = (
            [str(item) for item in interests_payload if isinstance(item, str)]
            if isinstance(interests_payload, list)
            else []
        )
        cited_by_count = value.get("cited_by_count")
        parsed_cited_by_count: int | None = None
        if isinstance(cited_by_count, int):
            parsed_cited_by_count = cited_by_count
        elif isinstance(cited_by_count, str) and cited_by_count.strip():
            try:
                parsed_cited_by_count = int(cited_by_count)
            except ValueError:
                parsed_cited_by_count = None
        normalized_candidates.append(
            {
                "scholar_id": scholar_id,
                "display_name": display_name,
                "affiliation": str(value.get("affiliation")).strip()
                if value.get("affiliation") is not None
                else None,
                "email_domain": str(value.get("email_domain")).strip()
                if value.get("email_domain") is not None
                else None,
                "cited_by_count": parsed_cited_by_count,
                "interests": interests,
                "profile_url": profile_url,
                "profile_image_url": str(value.get("profile_image_url")).strip()
                if value.get("profile_image_url") is not None
                else None,
            }
        )

    return ParsedAuthorSearchPage(
        state=state,
        state_reason=str(payload.get("state_reason", "")).strip() or "unknown",
        candidates=[
            ScholarSearchCandidate(
                scholar_id=item["scholar_id"],
                display_name=item["display_name"],
                affiliation=item["affiliation"],
                email_domain=item["email_domain"],
                cited_by_count=item["cited_by_count"],
                interests=item["interests"],
                profile_url=item["profile_url"],
                profile_image_url=item["profile_image_url"],
            )
            for item in normalized_candidates
        ],
        marker_counts=marker_counts,
        warnings=warnings,
    )


async def _cache_get_author_search_result(
    db_session: AsyncSession,
    *,
    query_key: str,
    now_utc: datetime,
) -> ParsedAuthorSearchPage | None:
    result = await db_session.execute(
        select(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.query_key == query_key)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    expires_at = entry.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now_utc:
        await db_session.delete(entry)
        return None
    parsed = _deserialize_parsed_author_search_page(entry.payload)
    if parsed is None:
        await db_session.delete(entry)
        return None
    return parsed


async def _cache_set_author_search_result(
    db_session: AsyncSession,
    *,
    query_key: str,
    parsed: ParsedAuthorSearchPage,
    ttl_seconds: float,
    max_entries: int,
    now_utc: datetime,
) -> None:
    ttl = max(float(ttl_seconds), 0.0)
    existing_result = await db_session.execute(
        select(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.query_key == query_key)
    )
    existing = existing_result.scalar_one_or_none()

    if ttl <= 0.0:
        if existing is not None:
            await db_session.delete(existing)
        return

    expires_at = now_utc + timedelta(seconds=ttl)
    payload = _serialize_parsed_author_search_page(parsed)
    if existing is None:
        db_session.add(
            AuthorSearchCacheEntry(
                query_key=query_key,
                payload=payload,
                expires_at=expires_at,
                cached_at=now_utc,
                updated_at=now_utc,
            )
        )
    else:
        existing.payload = payload
        existing.expires_at = expires_at
        existing.cached_at = now_utc
        existing.updated_at = now_utc

    await _prune_author_search_cache(db_session, now_utc=now_utc, max_entries=max_entries)


async def _prune_author_search_cache(
    db_session: AsyncSession,
    *,
    now_utc: datetime,
    max_entries: int,
) -> None:
    await db_session.execute(
        delete(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.expires_at <= now_utc)
    )
    bounded_max_entries = max(1, int(max_entries))
    count_result = await db_session.execute(
        select(func.count()).select_from(AuthorSearchCacheEntry)
    )
    entry_count = int(count_result.scalar_one() or 0)
    overflow = max(0, entry_count - bounded_max_entries)
    if overflow <= 0:
        return
    stale_keys_result = await db_session.execute(
        select(AuthorSearchCacheEntry.query_key)
        .order_by(AuthorSearchCacheEntry.cached_at.asc())
        .limit(overflow)
    )
    stale_keys = [str(row[0]) for row in stale_keys_result.all()]
    if stale_keys:
        await db_session.execute(
            delete(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.query_key.in_(stale_keys))
        )


def _is_author_search_block_state(parsed: ParsedAuthorSearchPage) -> bool:
    return parsed.state == ParseState.BLOCKED_OR_CAPTCHA


def _author_search_cooldown_remaining_seconds(
    runtime_state: AuthorSearchRuntimeState,
    now_utc: datetime,
) -> int:
    cooldown_until = runtime_state.cooldown_until
    if cooldown_until is None:
        return 0
    if cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
    remaining_seconds = int((cooldown_until - now_utc).total_seconds())
    return max(0, remaining_seconds)


def _reset_author_search_runtime_state_for_tests() -> None:
    # Runtime state now lives in the database; tests should reset via DB fixtures.
    return None


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
    db_session: AsyncSession,
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
    retry_alert_threshold: int = DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD,
    cooldown_rejection_alert_threshold: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD,
) -> ParsedAuthorSearchPage:
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

    await _acquire_author_search_lock(db_session)
    runtime_state = await _load_runtime_state_for_update(db_session)
    runtime_state_updated = False
    now_utc = datetime.now(timezone.utc)

    if runtime_state.cooldown_until is not None:
        cooldown_until = runtime_state.cooldown_until
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
            runtime_state.cooldown_until = cooldown_until
            runtime_state_updated = True
        if now_utc >= cooldown_until:
            logger.info(
                "scholar_search.cooldown_expired",
                extra={
                    "event": "scholar_search.cooldown_expired",
                    "cooldown_until_utc": cooldown_until.isoformat(),
                },
            )
            runtime_state.cooldown_until = None
            runtime_state.cooldown_rejection_count = 0
            runtime_state.cooldown_alert_emitted = False
            runtime_state_updated = True

    cooldown_remaining_seconds = _author_search_cooldown_remaining_seconds(runtime_state, now_utc)
    if cooldown_remaining_seconds > 0:
        runtime_state.cooldown_rejection_count = int(runtime_state.cooldown_rejection_count) + 1
        bounded_cooldown_rejection_alert_threshold = max(
            1,
            int(cooldown_rejection_alert_threshold),
        )
        if (
            int(runtime_state.cooldown_rejection_count) >= bounded_cooldown_rejection_alert_threshold
            and not bool(runtime_state.cooldown_alert_emitted)
        ):
            logger.error(
                "scholar_search.cooldown_rejection_threshold_exceeded",
                extra={
                    "event": "scholar_search.cooldown_rejection_threshold_exceeded",
                    "query": normalized_query,
                    "cooldown_rejection_count": int(runtime_state.cooldown_rejection_count),
                    "threshold": bounded_cooldown_rejection_alert_threshold,
                    "cooldown_until_utc": runtime_state.cooldown_until.isoformat()
                    if runtime_state.cooldown_until
                    else None,
                },
            )
            runtime_state.cooldown_alert_emitted = True
        runtime_state_updated = True

        logger.warning(
            "scholar_search.cooldown_active",
            extra={
                "event": "scholar_search.cooldown_active",
                "query": normalized_query,
                "cooldown_remaining_seconds": cooldown_remaining_seconds,
                "cooldown_until_utc": runtime_state.cooldown_until.isoformat()
                if runtime_state.cooldown_until
                else None,
            },
        )
        warning_codes = [
            "author_search_cooldown_active",
            f"author_search_cooldown_remaining_{cooldown_remaining_seconds}s",
        ]
        if bool(runtime_state.cooldown_alert_emitted):
            warning_codes.append("author_search_cooldown_alert_threshold_exceeded")
        if runtime_state_updated:
            await db_session.commit()
        return _policy_blocked_author_search_result(
            reason=SEARCH_COOLDOWN_REASON,
            warning_codes=warning_codes,
            limit=bounded_limit,
        )

    cached = await _cache_get_author_search_result(
        db_session,
        query_key=query_key,
        now_utc=now_utc,
    )
    if cached is not None:
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
        await db_session.commit()
        return _trim_author_search_result(
            cached,
            limit=bounded_limit,
            extra_warnings=["author_search_served_from_cache"],
            state_reason_override=state_reason_override,
        )

    if runtime_state.last_live_request_at is not None:
        last_live_request_at = runtime_state.last_live_request_at
        if last_live_request_at.tzinfo is None:
            last_live_request_at = last_live_request_at.replace(tzinfo=timezone.utc)
            runtime_state.last_live_request_at = last_live_request_at
            runtime_state_updated = True
        enforced_wait_seconds = (
            last_live_request_at + timedelta(seconds=max(float(min_interval_seconds), 0.0)) - now_utc
        ).total_seconds()
    else:
        enforced_wait_seconds = 0.0

    jitter_seconds = random.uniform(0.0, max(float(interval_jitter_seconds), 0.0))
    sleep_seconds = max(0.0, float(enforced_wait_seconds)) + jitter_seconds
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
    retry_scheduled_count = 0

    for attempt_index in range(max_attempts):
        fetch_result = await source.fetch_author_search_html(normalized_query, start=0)
        parsed = parse_author_search_page(fetch_result)
        if parsed.state != ParseState.NETWORK_ERROR or attempt_index >= max_attempts - 1:
            break

        retry_warnings.append("network_retry_scheduled_for_author_search")
        retry_scheduled_count += 1
        retry_sleep_seconds = max(float(retry_backoff_seconds), 0.0) * (2**attempt_index)
        if retry_sleep_seconds > 0:
            await asyncio.sleep(retry_sleep_seconds)

    runtime_state.last_live_request_at = datetime.now(timezone.utc)
    runtime_state_updated = True

    if parsed is None:
        raise ScholarServiceError("Unable to complete scholar author search.")

    merged_parsed = replace(
        parsed,
        warnings=_merge_warnings(parsed.warnings, retry_warnings),
    )

    bounded_retry_alert_threshold = max(1, int(retry_alert_threshold))
    if retry_scheduled_count >= bounded_retry_alert_threshold:
        logger.warning(
            "scholar_search.retry_threshold_exceeded",
            extra={
                "event": "scholar_search.retry_threshold_exceeded",
                "query": normalized_query,
                "retry_scheduled_count": retry_scheduled_count,
                "threshold": bounded_retry_alert_threshold,
                "final_state": merged_parsed.state.value,
                "final_state_reason": merged_parsed.state_reason,
            },
        )
        merged_parsed = replace(
            merged_parsed,
            warnings=_merge_warnings(
                merged_parsed.warnings,
                [f"author_search_retry_threshold_exceeded_{retry_scheduled_count}"],
            ),
        )

    if _is_author_search_block_state(merged_parsed):
        runtime_state.consecutive_blocked_count = int(runtime_state.consecutive_blocked_count) + 1
        logger.warning(
            "scholar_search.block_detected",
            extra={
                "event": "scholar_search.block_detected",
                "query": normalized_query,
                "state_reason": merged_parsed.state_reason,
                "consecutive_blocked_count": int(runtime_state.consecutive_blocked_count),
            },
        )
        if int(runtime_state.consecutive_blocked_count) >= max(1, int(cooldown_block_threshold)):
            runtime_state.cooldown_until = datetime.now(timezone.utc) + timedelta(
                seconds=max(60, int(cooldown_seconds))
            )
            runtime_state.consecutive_blocked_count = 0
            runtime_state.cooldown_rejection_count = 0
            runtime_state.cooldown_alert_emitted = False
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
                    "cooldown_until_utc": runtime_state.cooldown_until.isoformat()
                    if runtime_state.cooldown_until
                    else None,
                },
            )
    else:
        runtime_state.consecutive_blocked_count = 0

    ttl_seconds = (
        min(max(1, int(blocked_cache_ttl_seconds)), max(1, int(cache_ttl_seconds)))
        if _is_author_search_block_state(merged_parsed)
        else max(1, int(cache_ttl_seconds))
    )
    await _cache_set_author_search_result(
        db_session,
        query_key=query_key,
        parsed=merged_parsed,
        ttl_seconds=float(ttl_seconds),
        max_entries=cache_max_entries,
        now_utc=datetime.now(timezone.utc),
    )
    if runtime_state_updated:
        await db_session.commit()

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
