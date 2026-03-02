from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.api.routers import scholar_helpers


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_create_hydration_skips_when_global_throttle_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = SimpleNamespace(
        id=42,
        profile_image_url=None,
        display_name="",
    )

    async def _fail_hydration(*_args, **_kwargs):
        raise AssertionError("hydrate_profile_metadata should not run when throttle is active")

    monkeypatch.setattr(
        scholar_helpers.scholar_rate_limit,
        "remaining_scholar_slot_seconds",
        lambda **_kwargs: 3.5,
    )
    monkeypatch.setattr(
        scholar_helpers.scholar_service,
        "hydrate_profile_metadata",
        _fail_hydration,
    )

    result = await scholar_helpers.hydrate_scholar_metadata_if_needed(
        db_session=cast(Any, None),
        profile=profile,
        source=cast(Any, object()),
        user_id=7,
    )

    assert result is profile


@pytest.mark.asyncio
async def test_create_hydration_runs_when_throttle_is_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = SimpleNamespace(
        id=84,
        profile_image_url=None,
        display_name="",
    )

    async def _hydrate_profile_metadata(*_args, **_kwargs):
        profile.display_name = "Ada Lovelace"
        return profile

    monkeypatch.setattr(
        scholar_helpers.scholar_rate_limit,
        "remaining_scholar_slot_seconds",
        lambda **_kwargs: 0.0,
    )
    monkeypatch.setattr(
        scholar_helpers.scholar_service,
        "hydrate_profile_metadata",
        _hydrate_profile_metadata,
    )

    result = await scholar_helpers.hydrate_scholar_metadata_if_needed(
        db_session=cast(Any, None),
        profile=profile,
        source=cast(Any, object()),
        user_id=8,
    )

    assert result.display_name == "Ada Lovelace"


@pytest.mark.asyncio
async def test_initial_scrape_job_enqueued_on_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = SimpleNamespace(id=101)
    session = _FakeSession()
    upsert_calls: list[dict[str, object]] = []

    async def _fake_upsert_job(*_args, **kwargs):
        upsert_calls.append(kwargs)

    monkeypatch.setattr(
        scholar_helpers,
        "auto_enqueue_new_scholar_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        scholar_helpers.ingestion_queue_service,
        "upsert_job",
        _fake_upsert_job,
    )

    queued = await scholar_helpers.enqueue_initial_scrape_job_for_scholar(
        cast(Any, session),
        profile=profile,
        user_id=9,
    )

    assert queued is True
    assert session.commits == 1
    assert session.rollbacks == 0
    assert upsert_calls[0]["reason"] == scholar_helpers.INITIAL_SCHOLAR_SCRAPE_QUEUE_REASON


@pytest.mark.asyncio
async def test_initial_scrape_job_not_enqueued_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = SimpleNamespace(id=202)
    session = _FakeSession()

    monkeypatch.setattr(
        scholar_helpers,
        "auto_enqueue_new_scholar_enabled",
        lambda: False,
    )

    queued = await scholar_helpers.enqueue_initial_scrape_job_for_scholar(
        cast(Any, session),
        profile=profile,
        user_id=11,
    )

    assert queued is False
    assert session.commits == 0
    assert session.rollbacks == 0
