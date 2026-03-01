from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArxivRuntimeState
from app.db.session import get_session_factory
from app.logging_utils import structured_log
from app.services.arxiv.constants import (
    ARXIV_RATE_LIMIT_LOCK_KEY,
    ARXIV_RATE_LIMIT_LOCK_NAMESPACE,
    ARXIV_RUNTIME_STATE_KEY,
    ARXIV_SOURCE_PATH_UNKNOWN,
)
from app.services.arxiv.errors import ArxivRateLimitError
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArxivCooldownStatus:
    is_active: bool
    remaining_seconds: float
    cooldown_until: datetime | None


async def run_with_global_arxiv_limit(
    *,
    fetch: Callable[[], Awaitable[httpx.Response]],
    source_path: str = ARXIV_SOURCE_PATH_UNKNOWN,
) -> httpx.Response:
    response, hit_rate_limit = await _run_serialized_fetch(
        fetch=fetch,
        source_path=source_path,
    )
    if hit_rate_limit:
        raise ArxivRateLimitError("arXiv rate limit hit (429) — stopping batch")
    return response


async def get_arxiv_cooldown_status(*, now_utc: datetime | None = None) -> ArxivCooldownStatus:
    timestamp = _normalize_datetime(now_utc) or datetime.now(UTC)
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        result = await db_session.execute(
            select(ArxivRuntimeState.cooldown_until).where(ArxivRuntimeState.state_key == ARXIV_RUNTIME_STATE_KEY)
        )
    cooldown_until = _normalize_datetime(result.scalar_one_or_none())
    remaining_seconds = _cooldown_remaining_seconds(cooldown_until, now_utc=timestamp)
    return ArxivCooldownStatus(
        is_active=remaining_seconds > 0.0,
        remaining_seconds=float(remaining_seconds),
        cooldown_until=cooldown_until,
    )


async def _run_serialized_fetch(
    *,
    fetch: Callable[[], Awaitable[httpx.Response]],
    source_path: str,
) -> tuple[httpx.Response, bool]:
    session_factory = get_session_factory()
    async with session_factory() as db_session, db_session.begin():
        await _acquire_arxiv_lock(db_session)
        runtime_state = await _load_runtime_state_for_update(db_session)
        wait_seconds = await _wait_for_allowed_slot_or_raise(
            runtime_state,
            source_path=source_path,
        )
        runtime_state.next_allowed_at = datetime.now(UTC) + timedelta(seconds=_min_interval_seconds())

    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)
    response = await fetch()

    async with session_factory() as db_session, db_session.begin():
        runtime_state = await _load_runtime_state_for_update(db_session)
        hit_rate_limit = _record_post_response_state(
            runtime_state,
            response_status=int(response.status_code),
            source_path=source_path,
        )
    structured_log(
        logger,
        "info",
        "arxiv.request_completed",
        status_code=int(response.status_code),
        wait_seconds=wait_seconds,
        cooldown_remaining_seconds=_cooldown_remaining_seconds(
            runtime_state.cooldown_until, now_utc=datetime.now(UTC)
        ),
        source_path=source_path,
    )
    return response, hit_rate_limit


async def _acquire_arxiv_lock(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
        {
            "namespace": ARXIV_RATE_LIMIT_LOCK_NAMESPACE,
            "lock_key": ARXIV_RATE_LIMIT_LOCK_KEY,
        },
    )


async def _load_runtime_state_for_update(db_session: AsyncSession) -> ArxivRuntimeState:
    result = await db_session.execute(
        select(ArxivRuntimeState).where(ArxivRuntimeState.state_key == ARXIV_RUNTIME_STATE_KEY).with_for_update()
    )
    state = result.scalar_one_or_none()
    if state is not None:
        return state
    state = ArxivRuntimeState(state_key=ARXIV_RUNTIME_STATE_KEY)
    db_session.add(state)
    await db_session.flush()
    return state


async def _wait_for_allowed_slot_or_raise(
    runtime_state: ArxivRuntimeState,
    *,
    source_path: str,
) -> float:
    now_utc = datetime.now(UTC)
    cooldown_seconds = _cooldown_remaining_seconds(runtime_state.cooldown_until, now_utc=now_utc)
    if cooldown_seconds > 0:
        structured_log(
            logger,
            "info",
            "arxiv.request_scheduled",
            wait_seconds=0.0,
            source_path=source_path,
            cooldown_remaining_seconds=cooldown_seconds,
        )
        raise ArxivRateLimitError(f"arXiv global cooldown active ({cooldown_seconds:.0f}s remaining)")
    wait_seconds = _next_allowed_wait_seconds(runtime_state.next_allowed_at, now_utc=now_utc)
    structured_log(
        logger,
        "info",
        "arxiv.request_scheduled",
        wait_seconds=wait_seconds,
        source_path=source_path,
        cooldown_remaining_seconds=0.0,
    )
    return wait_seconds


def _record_post_response_state(
    runtime_state: ArxivRuntimeState,
    *,
    response_status: int,
    source_path: str,
) -> bool:
    now_utc = datetime.now(UTC)
    runtime_state.next_allowed_at = now_utc + timedelta(seconds=_min_interval_seconds())
    if response_status == 429:
        cooldown_seconds = _cooldown_seconds()
        runtime_state.cooldown_until = now_utc + timedelta(seconds=cooldown_seconds)
        structured_log(
            logger,
            "warning",
            "arxiv.cooldown_activated",
            cooldown_remaining_seconds=cooldown_seconds,
            source_path=source_path,
        )
        return True
    if _cooldown_remaining_seconds(runtime_state.cooldown_until, now_utc=now_utc) <= 0:
        runtime_state.cooldown_until = None
    return False


def _cooldown_remaining_seconds(cooldown_until: datetime | None, *, now_utc: datetime) -> float:
    bounded = _normalize_datetime(cooldown_until)
    if bounded is None:
        return 0.0
    return max((bounded - now_utc).total_seconds(), 0.0)


def _next_allowed_wait_seconds(next_allowed_at: datetime | None, *, now_utc: datetime) -> float:
    bounded = _normalize_datetime(next_allowed_at)
    if bounded is None:
        return 0.0
    return max((bounded - now_utc).total_seconds(), 0.0)


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _min_interval_seconds() -> float:
    return max(float(settings.arxiv_min_interval_seconds), 0.0)


def _cooldown_seconds() -> float:
    return max(float(settings.arxiv_rate_limit_cooldown_seconds), 0.0)
