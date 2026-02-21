from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import random
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthorSearchCacheEntry, AuthorSearchRuntimeState, ScholarProfile
from app.services.domains.scholar.parser import (
    ParseState,
    ParsedAuthorSearchPage,
    ScholarParserError,
    parse_author_search_page,
    parse_profile_page,
)
from app.services.domains.scholar.source import ScholarSource
from app.services.domains.scholars.constants import (
    ALLOWED_IMAGE_UPLOAD_CONTENT_TYPES,
    AUTHOR_SEARCH_LOCK_KEY,
    AUTHOR_SEARCH_LOCK_NAMESPACE,
    AUTHOR_SEARCH_RUNTIME_STATE_KEY,
    DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS,
    DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES,
    DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD,
    DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD,
    DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS,
    DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS,
    MAX_AUTHOR_SEARCH_LIMIT,
    DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS,
    DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD,
    SEARCH_CACHED_BLOCK_REASON,
    SEARCH_COOLDOWN_REASON,
    SEARCH_DISABLED_REASON,
)
from app.services.domains.scholars.exceptions import ScholarServiceError
from app.services.domains.scholars.search_hints import (
    _merge_warnings,
    _policy_blocked_author_search_result,
    _trim_author_search_result,
    resolve_profile_image,
    scrape_state_hint,
)
from app.services.domains.scholars.uploads import (
    _ensure_upload_root,
    _resolve_upload_path,
    _safe_remove_upload,
    resolve_upload_file_path,
)
from app.services.domains.scholars.validators import (
    normalize_display_name,
    normalize_profile_image_url,
    validate_scholar_id,
)
logger = logging.getLogger(__name__)


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


def _payload_state(payload: dict[str, object]) -> ParseState | None:
    state_raw = str(payload.get("state", "")).strip()
    try:
        return ParseState(state_raw)
    except ValueError:
        return None


def _payload_marker_counts(payload: dict[str, object]) -> dict[str, int]:
    marker_counts_payload = payload.get("marker_counts")
    if not isinstance(marker_counts_payload, dict):
        return {}
    parsed: dict[str, int] = {}
    for key, value in marker_counts_payload.items():
        try:
            parsed[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return parsed


def _payload_warnings(payload: dict[str, object]) -> list[str]:
    warnings_payload = payload.get("warnings")
    if not isinstance(warnings_payload, list):
        return []
    return [str(value) for value in warnings_payload if isinstance(value, str)]


def _parse_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _normalize_interests(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _deserialize_candidate_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    scholar_id = str(value.get("scholar_id", "")).strip()
    display_name = str(value.get("display_name", "")).strip()
    profile_url = str(value.get("profile_url", "")).strip()
    if not scholar_id or not display_name or not profile_url:
        return None
    return {
        "scholar_id": scholar_id,
        "display_name": display_name,
        "affiliation": _parse_optional_string(value.get("affiliation")),
        "email_domain": _parse_optional_string(value.get("email_domain")),
        "cited_by_count": _parse_optional_int(value.get("cited_by_count")),
        "interests": _normalize_interests(value.get("interests")),
        "profile_url": profile_url,
        "profile_image_url": _parse_optional_string(value.get("profile_image_url")),
    }


def _deserialize_candidates(payload: dict[str, object]) -> list[dict[str, object]]:
    candidates_payload = payload.get("candidates")
    if not isinstance(candidates_payload, list):
        return []
    normalized: list[dict[str, object]] = []
    for value in candidates_payload:
        candidate = _deserialize_candidate_payload(value)
        if candidate is not None:
            normalized.append(candidate)
    return normalized


def _deserialize_parsed_author_search_page(payload: object) -> ParsedAuthorSearchPage | None:
    if not isinstance(payload, dict):
        return None

    state = _payload_state(payload)
    if state is None:
        return None

    marker_counts = _payload_marker_counts(payload)
    warnings = _payload_warnings(payload)
    from app.services.domains.scholar.parser import ScholarSearchCandidate

    normalized_candidates = _deserialize_candidates(payload)

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


def _normalize_author_search_inputs(query: str, limit: int) -> tuple[str, int, str]:
    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise ScholarServiceError("Search query must be at least 2 characters.")
    bounded_limit = max(1, min(int(limit), MAX_AUTHOR_SEARCH_LIMIT))
    return normalized_query, bounded_limit, normalized_query.casefold()


def _disabled_search_result(*, normalized_query: str, bounded_limit: int) -> ParsedAuthorSearchPage:
    logger.warning(
        "scholar_search.disabled_by_configuration",
        extra={"event": "scholar_search.disabled_by_configuration", "query": normalized_query},
    )
    return _policy_blocked_author_search_result(
        reason=SEARCH_DISABLED_REASON,
        warning_codes=["author_search_disabled_by_configuration"],
        limit=bounded_limit,
    )


def _normalize_runtime_cooldown_state(
    runtime_state: AuthorSearchRuntimeState,
    *,
    now_utc: datetime,
) -> bool:
    if runtime_state.cooldown_until is None:
        return False
    cooldown_until = runtime_state.cooldown_until
    updated = False
    if cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
        runtime_state.cooldown_until = cooldown_until
        updated = True
    if now_utc < cooldown_until:
        return updated
    logger.info(
        "scholar_search.cooldown_expired",
        extra={"event": "scholar_search.cooldown_expired", "cooldown_until_utc": cooldown_until.isoformat()},
    )
    runtime_state.cooldown_until = None
    runtime_state.cooldown_rejection_count = 0
    runtime_state.cooldown_alert_emitted = False
    return True


def _cooldown_warning_codes(
    *,
    runtime_state: AuthorSearchRuntimeState,
    cooldown_remaining_seconds: int,
) -> list[str]:
    warning_codes = [
        "author_search_cooldown_active",
        f"author_search_cooldown_remaining_{cooldown_remaining_seconds}s",
    ]
    if bool(runtime_state.cooldown_alert_emitted):
        warning_codes.append("author_search_cooldown_alert_threshold_exceeded")
    return warning_codes


def _emit_cooldown_threshold_alert(
    *,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    cooldown_rejection_alert_threshold: int,
) -> bool:
    runtime_state.cooldown_rejection_count = int(runtime_state.cooldown_rejection_count) + 1
    threshold = max(1, int(cooldown_rejection_alert_threshold))
    if int(runtime_state.cooldown_rejection_count) < threshold:
        return True
    if bool(runtime_state.cooldown_alert_emitted):
        return True
    logger.error(
        "scholar_search.cooldown_rejection_threshold_exceeded",
        extra={
            "event": "scholar_search.cooldown_rejection_threshold_exceeded",
            "query": normalized_query,
            "cooldown_rejection_count": int(runtime_state.cooldown_rejection_count),
            "threshold": threshold,
            "cooldown_until_utc": runtime_state.cooldown_until.isoformat() if runtime_state.cooldown_until else None,
        },
    )
    runtime_state.cooldown_alert_emitted = True
    return True


def _cooldown_block_result(
    *,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    bounded_limit: int,
    cooldown_rejection_alert_threshold: int,
    cooldown_remaining_seconds: int,
) -> ParsedAuthorSearchPage:
    _emit_cooldown_threshold_alert(
        runtime_state=runtime_state,
        normalized_query=normalized_query,
        cooldown_rejection_alert_threshold=cooldown_rejection_alert_threshold,
    )
    logger.warning(
        "scholar_search.cooldown_active",
        extra={
            "event": "scholar_search.cooldown_active",
            "query": normalized_query,
            "cooldown_remaining_seconds": cooldown_remaining_seconds,
            "cooldown_until_utc": runtime_state.cooldown_until.isoformat() if runtime_state.cooldown_until else None,
        },
    )
    return _policy_blocked_author_search_result(
        reason=SEARCH_COOLDOWN_REASON,
        warning_codes=_cooldown_warning_codes(
            runtime_state=runtime_state,
            cooldown_remaining_seconds=cooldown_remaining_seconds,
        ),
        limit=bounded_limit,
    )


async def _cache_hit_result(
    db_session: AsyncSession,
    *,
    query_key: str,
    now_utc: datetime,
    normalized_query: str,
    bounded_limit: int,
) -> ParsedAuthorSearchPage | None:
    cached = await _cache_get_author_search_result(
        db_session,
        query_key=query_key,
        now_utc=now_utc,
    )
    if cached is None:
        return None
    logger.info(
        "scholar_search.cache_hit",
        extra={
            "event": "scholar_search.cache_hit",
            "query": normalized_query,
            "state": cached.state.value,
            "state_reason": cached.state_reason,
        },
    )
    state_reason_override = SEARCH_CACHED_BLOCK_REASON if _is_author_search_block_state(cached) else None
    return _trim_author_search_result(
        cached,
        limit=bounded_limit,
        extra_warnings=["author_search_served_from_cache"],
        state_reason_override=state_reason_override,
    )


def _throttle_sleep_seconds(
    *,
    runtime_state: AuthorSearchRuntimeState,
    now_utc: datetime,
    min_interval_seconds: float,
    interval_jitter_seconds: float,
) -> tuple[float, bool]:
    updated = False
    if runtime_state.last_live_request_at is None:
        enforced_wait_seconds = 0.0
    else:
        last_live_request_at = runtime_state.last_live_request_at
        if last_live_request_at.tzinfo is None:
            last_live_request_at = last_live_request_at.replace(tzinfo=timezone.utc)
            runtime_state.last_live_request_at = last_live_request_at
            updated = True
        enforced_wait_seconds = (
            last_live_request_at + timedelta(seconds=max(float(min_interval_seconds), 0.0)) - now_utc
        ).total_seconds()
    jitter_seconds = random.uniform(0.0, max(float(interval_jitter_seconds), 0.0))
    return max(0.0, float(enforced_wait_seconds)) + jitter_seconds, updated


async def _wait_for_author_search_throttle(
    *,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    now_utc: datetime,
    min_interval_seconds: float,
    interval_jitter_seconds: float,
) -> bool:
    sleep_seconds, updated = _throttle_sleep_seconds(
        runtime_state=runtime_state,
        now_utc=now_utc,
        min_interval_seconds=min_interval_seconds,
        interval_jitter_seconds=interval_jitter_seconds,
    )
    if sleep_seconds <= 0.0:
        return updated
    logger.info(
        "scholar_search.throttle_wait",
        extra={"event": "scholar_search.throttle_wait", "query": normalized_query, "sleep_seconds": round(sleep_seconds, 3)},
    )
    await asyncio.sleep(sleep_seconds)
    return True


async def _fetch_author_search_with_retries(
    *,
    source: ScholarSource,
    normalized_query: str,
    network_error_retries: int,
    retry_backoff_seconds: float,
) -> tuple[ParsedAuthorSearchPage, int, list[str]]:
    max_attempts = max(1, int(network_error_retries) + 1)
    parsed: ParsedAuthorSearchPage | None = None
    retry_warnings: list[str] = []
    retry_scheduled_count = 0
    for attempt_index in range(max_attempts):
        fetch_result = await source.fetch_author_search_html(normalized_query, start=0)
        try:
            parsed = parse_author_search_page(fetch_result)
        except ScholarParserError as exc:
            parsed = ParsedAuthorSearchPage(
                state=ParseState.LAYOUT_CHANGED,
                state_reason=exc.code,
                candidates=[],
                marker_counts={},
                warnings=[exc.code],
            )
        if parsed.state != ParseState.NETWORK_ERROR or attempt_index >= max_attempts - 1:
            break
        retry_warnings.append("network_retry_scheduled_for_author_search")
        retry_scheduled_count += 1
        retry_sleep_seconds = max(float(retry_backoff_seconds), 0.0) * (2**attempt_index)
        if retry_sleep_seconds > 0:
            await asyncio.sleep(retry_sleep_seconds)
    if parsed is None:
        raise ScholarServiceError("Unable to complete scholar author search.")
    return parsed, retry_scheduled_count, retry_warnings


def _with_retry_warnings(
    parsed: ParsedAuthorSearchPage,
    *,
    retry_warnings: list[str],
    retry_scheduled_count: int,
    retry_alert_threshold: int,
    normalized_query: str,
) -> ParsedAuthorSearchPage:
    merged = replace(parsed, warnings=_merge_warnings(parsed.warnings, retry_warnings))
    threshold = max(1, int(retry_alert_threshold))
    if retry_scheduled_count < threshold:
        return merged
    logger.warning(
        "scholar_search.retry_threshold_exceeded",
        extra={
            "event": "scholar_search.retry_threshold_exceeded",
            "query": normalized_query,
            "retry_scheduled_count": retry_scheduled_count,
            "threshold": threshold,
            "final_state": merged.state.value,
            "final_state_reason": merged.state_reason,
        },
    )
    return replace(
        merged,
        warnings=_merge_warnings(
            merged.warnings,
            [f"author_search_retry_threshold_exceeded_{retry_scheduled_count}"],
        ),
    )


def _apply_block_circuit_breaker(
    *,
    runtime_state: AuthorSearchRuntimeState,
    merged_parsed: ParsedAuthorSearchPage,
    cooldown_block_threshold: int,
    cooldown_seconds: int,
    normalized_query: str,
) -> ParsedAuthorSearchPage:
    if not _is_author_search_block_state(merged_parsed):
        runtime_state.consecutive_blocked_count = 0
        return merged_parsed
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
    if int(runtime_state.consecutive_blocked_count) < max(1, int(cooldown_block_threshold)):
        return merged_parsed
    runtime_state.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=max(60, int(cooldown_seconds)))
    runtime_state.consecutive_blocked_count = 0
    runtime_state.cooldown_rejection_count = 0
    runtime_state.cooldown_alert_emitted = False
    logger.error(
        "scholar_search.cooldown_activated",
        extra={
            "event": "scholar_search.cooldown_activated",
            "query": normalized_query,
            "cooldown_until_utc": runtime_state.cooldown_until.isoformat() if runtime_state.cooldown_until else None,
        },
    )
    return replace(
        merged_parsed,
        warnings=_merge_warnings(merged_parsed.warnings, ["author_search_circuit_breaker_armed"]),
    )


def _resolve_author_search_cache_ttl_seconds(
    *,
    merged_parsed: ParsedAuthorSearchPage,
    blocked_cache_ttl_seconds: int,
    cache_ttl_seconds: int,
) -> int:
    if _is_author_search_block_state(merged_parsed):
        return min(max(1, int(blocked_cache_ttl_seconds)), max(1, int(cache_ttl_seconds)))
    return max(1, int(cache_ttl_seconds))


async def _load_locked_runtime_state(
    db_session: AsyncSession,
) -> AuthorSearchRuntimeState:
    await _acquire_author_search_lock(db_session)
    return await _load_runtime_state_for_update(db_session)


async def _cooldown_or_cache_result(
    db_session: AsyncSession,
    *,
    runtime_state: AuthorSearchRuntimeState,
    query_key: str,
    normalized_query: str,
    bounded_limit: int,
    cooldown_rejection_alert_threshold: int,
) -> tuple[ParsedAuthorSearchPage | None, bool]:
    runtime_state_updated = _normalize_runtime_cooldown_state(
        runtime_state,
        now_utc=datetime.now(timezone.utc),
    )
    cooldown_remaining_seconds = _author_search_cooldown_remaining_seconds(
        runtime_state,
        datetime.now(timezone.utc),
    )
    if cooldown_remaining_seconds > 0:
        return (
            _cooldown_block_result(
                runtime_state=runtime_state,
                normalized_query=normalized_query,
                bounded_limit=bounded_limit,
                cooldown_rejection_alert_threshold=cooldown_rejection_alert_threshold,
                cooldown_remaining_seconds=cooldown_remaining_seconds,
            ),
            True,
        )
    cached_result = await _cache_hit_result(
        db_session,
        query_key=query_key,
        now_utc=datetime.now(timezone.utc),
        normalized_query=normalized_query,
        bounded_limit=bounded_limit,
    )
    return cached_result, runtime_state_updated


async def _perform_live_author_search(db_session: AsyncSession, *, source: ScholarSource, runtime_state: AuthorSearchRuntimeState, normalized_query: str, query_key: str, network_error_retries: int, retry_backoff_seconds: float, min_interval_seconds: float, interval_jitter_seconds: float, retry_alert_threshold: int, cooldown_block_threshold: int, cooldown_seconds: int, blocked_cache_ttl_seconds: int, cache_ttl_seconds: int, cache_max_entries: int) -> tuple[ParsedAuthorSearchPage, bool]:
    runtime_state_updated = await _wait_for_author_search_throttle(
        runtime_state=runtime_state,
        normalized_query=normalized_query,
        now_utc=datetime.now(timezone.utc),
        min_interval_seconds=min_interval_seconds,
        interval_jitter_seconds=interval_jitter_seconds,
    )
    parsed, retry_count, retry_warnings = await _fetch_author_search_with_retries(
        source=source,
        normalized_query=normalized_query,
        network_error_retries=network_error_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    runtime_state.last_live_request_at = datetime.now(timezone.utc)
    merged = _with_retry_warnings(
        parsed,
        retry_warnings=retry_warnings,
        retry_scheduled_count=retry_count,
        retry_alert_threshold=retry_alert_threshold,
        normalized_query=normalized_query,
    )
    merged = _apply_block_circuit_breaker(
        runtime_state=runtime_state,
        merged_parsed=merged,
        cooldown_block_threshold=cooldown_block_threshold,
        cooldown_seconds=cooldown_seconds,
        normalized_query=normalized_query,
    )
    ttl_seconds = _resolve_author_search_cache_ttl_seconds(
        merged_parsed=merged,
        blocked_cache_ttl_seconds=blocked_cache_ttl_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    await _cache_set_author_search_result(
        db_session,
        query_key=query_key,
        parsed=merged,
        ttl_seconds=float(ttl_seconds),
        max_entries=cache_max_entries,
        now_utc=datetime.now(timezone.utc),
    )
    return merged, True


async def search_author_candidates(*, source: ScholarSource, db_session: AsyncSession, query: str, limit: int, network_error_retries: int = 1, retry_backoff_seconds: float = 1.0, search_enabled: bool = True, cache_ttl_seconds: int = 21_600, blocked_cache_ttl_seconds: int = DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS, cache_max_entries: int = DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES, min_interval_seconds: float = DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS, interval_jitter_seconds: float = DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS, cooldown_block_threshold: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD, cooldown_seconds: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS, retry_alert_threshold: int = DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD, cooldown_rejection_alert_threshold: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD) -> ParsedAuthorSearchPage:
    normalized_query, bounded_limit, query_key = _normalize_author_search_inputs(query, limit)
    if not search_enabled:
        return _disabled_search_result(
            normalized_query=normalized_query,
            bounded_limit=bounded_limit,
        )

    runtime_state = await _load_locked_runtime_state(db_session)
    early_result, runtime_state_updated = await _cooldown_or_cache_result(
        db_session,
        runtime_state=runtime_state,
        query_key=query_key,
        normalized_query=normalized_query,
        bounded_limit=bounded_limit,
        cooldown_rejection_alert_threshold=cooldown_rejection_alert_threshold,
    )
    if early_result is not None:
        await db_session.commit()
        return early_result

    merged_parsed, live_runtime_updated = await _perform_live_author_search(
        db_session,
        source=source,
        runtime_state=runtime_state,
        normalized_query=normalized_query,
        query_key=query_key,
        network_error_retries=network_error_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        min_interval_seconds=min_interval_seconds,
        interval_jitter_seconds=interval_jitter_seconds,
        retry_alert_threshold=retry_alert_threshold,
        cooldown_block_threshold=cooldown_block_threshold,
        cooldown_seconds=cooldown_seconds,
        blocked_cache_ttl_seconds=blocked_cache_ttl_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
        cache_max_entries=cache_max_entries,
    )
    runtime_state_updated = runtime_state_updated or live_runtime_updated
    if runtime_state_updated:
        await db_session.commit()
    return _trim_author_search_result(merged_parsed, limit=bounded_limit)


async def hydrate_profile_metadata(
    db_session: AsyncSession,
    *,
    profile: ScholarProfile,
    source: ScholarSource,
) -> ScholarProfile:
    fetch_result = await source.fetch_profile_html(profile.scholar_id)
    try:
        parsed_page = parse_profile_page(fetch_result)
    except ScholarParserError:
        return profile

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
