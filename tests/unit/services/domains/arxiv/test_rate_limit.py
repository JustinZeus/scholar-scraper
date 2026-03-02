from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArxivRuntimeState
from app.services.arxiv.constants import ARXIV_RUNTIME_STATE_KEY
from app.services.arxiv.errors import ArxivRateLimitError
from app.services.arxiv.rate_limit import get_arxiv_cooldown_status, run_with_global_arxiv_limit
from app.settings import settings


@pytest.mark.asyncio
async def test_arxiv_rate_limit_respects_cooldown(db_session: AsyncSession, patch_session_factory) -> None:
    db_session.add(
        ArxivRuntimeState(
            state_key=ARXIV_RUNTIME_STATE_KEY,
            cooldown_until=datetime.now(UTC) + timedelta(seconds=30),
        )
    )
    await db_session.commit()

    called = {"count": 0}

    async def _fetch() -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, text="ok")

    with pytest.raises(ArxivRateLimitError):
        await run_with_global_arxiv_limit(fetch=_fetch)
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_arxiv_rate_limit_persists_cooldown_after_429(db_session: AsyncSession, patch_session_factory) -> None:
    previous_interval = settings.arxiv_min_interval_seconds
    previous_cooldown = settings.arxiv_rate_limit_cooldown_seconds
    object.__setattr__(settings, "arxiv_min_interval_seconds", 0.0)
    object.__setattr__(settings, "arxiv_rate_limit_cooldown_seconds", 5.0)
    try:

        async def _fetch() -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        with pytest.raises(ArxivRateLimitError):
            await run_with_global_arxiv_limit(fetch=_fetch)
    finally:
        object.__setattr__(settings, "arxiv_min_interval_seconds", previous_interval)
        object.__setattr__(settings, "arxiv_rate_limit_cooldown_seconds", previous_cooldown)

    result = await db_session.execute(
        select(ArxivRuntimeState).where(ArxivRuntimeState.state_key == ARXIV_RUNTIME_STATE_KEY)
    )
    state = result.scalar_one()
    assert state.cooldown_until is not None
    assert state.cooldown_until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_arxiv_rate_limit_serializes_concurrent_calls(db_session: AsyncSession, patch_session_factory) -> None:
    previous_interval = settings.arxiv_min_interval_seconds
    previous_cooldown = settings.arxiv_rate_limit_cooldown_seconds
    object.__setattr__(settings, "arxiv_min_interval_seconds", 0.2)
    object.__setattr__(settings, "arxiv_rate_limit_cooldown_seconds", 5.0)
    try:
        call_times: list[float] = []

        async def _fetch() -> httpx.Response:
            call_times.append(asyncio.get_running_loop().time())
            return httpx.Response(200, text="ok")

        await asyncio.gather(
            run_with_global_arxiv_limit(fetch=_fetch),
            run_with_global_arxiv_limit(fetch=_fetch),
        )
    finally:
        object.__setattr__(settings, "arxiv_min_interval_seconds", previous_interval)
        object.__setattr__(settings, "arxiv_rate_limit_cooldown_seconds", previous_cooldown)

    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= 0.18


@pytest.mark.asyncio
async def test_arxiv_rate_limit_logs_request_scheduled_and_completed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    patch_session_factory,
) -> None:
    logged: list[dict[str, object]] = []

    async def _fetch() -> httpx.Response:
        return httpx.Response(200, text="ok")

    def _capture_log(_msg: str, *args, **kwargs) -> None:
        logged.append({"event": _msg, **(kwargs.get("extra") or {})})

    monkeypatch.setattr("app.services.arxiv.rate_limit.logger.info", _capture_log)
    await run_with_global_arxiv_limit(fetch=_fetch, source_path="search")

    scheduled = [entry for entry in logged if entry.get("event") == "arxiv.request_scheduled"]
    completed = [entry for entry in logged if entry.get("event") == "arxiv.request_completed"]

    assert scheduled
    assert completed
    assert float(str(scheduled[0]["wait_seconds"])) >= 0.0
    assert int(str(completed[0]["status_code"])) == 200
    assert completed[0]["source_path"] == "search"


@pytest.mark.asyncio
async def test_arxiv_rate_limit_logs_cooldown_activation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    patch_session_factory,
) -> None:
    logged_warning: list[dict[str, object]] = []
    previous_interval = settings.arxiv_min_interval_seconds
    previous_cooldown = settings.arxiv_rate_limit_cooldown_seconds
    object.__setattr__(settings, "arxiv_min_interval_seconds", 0.0)
    object.__setattr__(settings, "arxiv_rate_limit_cooldown_seconds", 5.0)
    try:

        async def _fetch() -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        def _capture_warning(_msg: str, *args, **kwargs) -> None:
            logged_warning.append({"event": _msg, **(kwargs.get("extra") or {})})

        monkeypatch.setattr("app.services.arxiv.rate_limit.logger.warning", _capture_warning)
        with pytest.raises(ArxivRateLimitError):
            await run_with_global_arxiv_limit(fetch=_fetch, source_path="lookup_ids")
    finally:
        object.__setattr__(settings, "arxiv_min_interval_seconds", previous_interval)
        object.__setattr__(settings, "arxiv_rate_limit_cooldown_seconds", previous_cooldown)

    cooldown_events = [entry for entry in logged_warning if entry.get("event") == "arxiv.cooldown_activated"]
    assert cooldown_events
    assert cooldown_events[0]["source_path"] == "lookup_ids"
    assert float(str(cooldown_events[0]["cooldown_remaining_seconds"])) > 0.0


@pytest.mark.asyncio
async def test_get_arxiv_cooldown_status_reads_active_cooldown(db_session: AsyncSession, patch_session_factory) -> None:
    now_utc = datetime(2026, 2, 26, 13, 0, tzinfo=UTC)
    existing = await db_session.get(ArxivRuntimeState, ARXIV_RUNTIME_STATE_KEY)
    if existing is None:
        db_session.add(
            ArxivRuntimeState(
                state_key=ARXIV_RUNTIME_STATE_KEY,
                cooldown_until=now_utc + timedelta(seconds=45),
            )
        )
    else:
        existing.cooldown_until = now_utc + timedelta(seconds=45)
    await db_session.commit()

    status = await get_arxiv_cooldown_status(now_utc=now_utc)

    assert status.is_active is True
    assert status.cooldown_until is not None
    assert int(status.remaining_seconds) == 45
