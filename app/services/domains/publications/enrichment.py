from __future__ import annotations

import asyncio
import logging
import time

from app.db.session import get_session_factory
from app.services.domains.publications.listing import (
    missing_pdf_items,
    resolve_and_persist_oa_metadata,
)
from app.services.domains.publications.types import PublicationListItem
from app.settings import settings

logger = logging.getLogger(__name__)

_enrichment_lock = asyncio.Lock()
_inflight_publications: set[tuple[int, int]] = set()
_recent_attempt_seconds: dict[tuple[int, int], float] = {}
_scheduled_tasks: set[asyncio.Task[None]] = set()


def _cooldown_seconds() -> float:
    return max(float(settings.unpaywall_retry_cooldown_seconds), 1.0)


def _prune_recent_attempts(now_seconds: float, *, cooldown_seconds: float) -> None:
    expiry = cooldown_seconds * 3
    stale_keys = [
        key for key, attempted_seconds in _recent_attempt_seconds.items()
        if now_seconds - attempted_seconds >= expiry
    ]
    for key in stale_keys:
        _recent_attempt_seconds.pop(key, None)


async def _claim_items(
    *,
    user_id: int,
    items: list[PublicationListItem],
    max_items: int,
) -> list[PublicationListItem]:
    candidates = missing_pdf_items(items, limit=max_items)
    if not candidates:
        return []
    now_seconds = time.monotonic()
    cooldown_seconds = _cooldown_seconds()
    claimed: list[PublicationListItem] = []
    async with _enrichment_lock:
        _prune_recent_attempts(now_seconds, cooldown_seconds=cooldown_seconds)
        for item in candidates:
            key = (user_id, item.publication_id)
            attempted_seconds = _recent_attempt_seconds.get(key)
            if key in _inflight_publications:
                continue
            if attempted_seconds is not None and now_seconds - attempted_seconds < cooldown_seconds:
                continue
            _inflight_publications.add(key)
            _recent_attempt_seconds[key] = now_seconds
            claimed.append(item)
    return claimed


async def _release_claims(*, user_id: int, publication_ids: list[int]) -> None:
    async with _enrichment_lock:
        for publication_id in publication_ids:
            _inflight_publications.discard((user_id, publication_id))


def _on_task_done(task: asyncio.Task[None]) -> None:
    _scheduled_tasks.discard(task)
    try:
        task.result()
    except Exception:
        logger.exception(
            "publications.enrichment.task_failed",
            extra={"event": "publications.enrichment.task_failed"},
        )


async def _run_enrichment(
    *,
    user_id: int,
    request_email: str | None,
    items: list[PublicationListItem],
) -> None:
    publication_ids = [item.publication_id for item in items]
    try:
        session_factory = get_session_factory()
        async with session_factory() as db_session:
            await resolve_and_persist_oa_metadata(
                db_session,
                rows=items,
                unpaywall_email=request_email,
            )
    finally:
        await _release_claims(user_id=user_id, publication_ids=publication_ids)
        logger.info(
            "publications.enrichment.completed",
            extra={
                "event": "publications.enrichment.completed",
                "user_id": user_id,
                "publication_count": len(items),
            },
        )


async def schedule_missing_pdf_enrichment_for_user(
    *,
    user_id: int,
    request_email: str | None,
    items: list[PublicationListItem],
    max_items: int,
) -> int:
    claimed_items = await _claim_items(user_id=user_id, items=items, max_items=max_items)
    if not claimed_items:
        return 0
    task = asyncio.create_task(
        _run_enrichment(
            user_id=user_id,
            request_email=request_email,
            items=claimed_items,
        )
    )
    _scheduled_tasks.add(task)
    task.add_done_callback(_on_task_done)
    logger.info(
        "publications.enrichment.scheduled",
        extra={
            "event": "publications.enrichment.scheduled",
            "user_id": user_id,
            "publication_count": len(claimed_items),
        },
    )
    return len(claimed_items)
