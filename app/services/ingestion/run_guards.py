from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    RunTriggerType,
    ScholarProfile,
)
from app.logging_utils import structured_log
from app.services.ingestion import safety as run_safety_service
from app.services.ingestion.preflight import check_scholar_reachable
from app.services.ingestion.types import RunBlockedBySafetyPolicyError
from app.services.scholar.source import ScholarSource
from app.services.settings import application as user_settings_service
from app.settings import settings

logger = logging.getLogger(__name__)


async def load_user_settings_for_run(
    db_session: AsyncSession,
    *,
    user_id: int,
    trigger_type: RunTriggerType,
):
    user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=user_id)
    await enforce_safety_gate(db_session, user_settings=user_settings, user_id=user_id, trigger_type=trigger_type)
    return user_settings


async def enforce_safety_gate(
    db_session: AsyncSession,
    *,
    user_settings,
    user_id: int,
    trigger_type: RunTriggerType,
) -> None:
    now_utc = datetime.now(UTC)
    previous = run_safety_service.get_safety_event_context(user_settings, now_utc=now_utc)
    if run_safety_service.clear_expired_cooldown(user_settings, now_utc=now_utc):
        await db_session.commit()
        await db_session.refresh(user_settings)
        structured_log(
            logger,
            "info",
            "ingestion.cooldown_cleared",
            user_id=user_id,
            reason=previous.get("cooldown_reason"),
            cooldown_until=previous.get("cooldown_until"),
        )
        now_utc = datetime.now(UTC)
    if run_safety_service.is_cooldown_active(user_settings, now_utc=now_utc):
        await raise_safety_blocked_start(
            db_session,
            user_settings=user_settings,
            user_id=user_id,
            trigger_type=trigger_type,
            now_utc=now_utc,
        )


async def raise_safety_blocked_start(
    db_session: AsyncSession,
    *,
    user_settings,
    user_id: int,
    trigger_type: RunTriggerType,
    now_utc: datetime,
) -> None:
    safety_state = run_safety_service.register_cooldown_blocked_start(user_settings, now_utc=now_utc)
    await db_session.commit()
    structured_log(
        logger,
        "warning",
        "ingestion.safety_policy_blocked_run_start",
        user_id=user_id,
        trigger_type=trigger_type.value,
        reason=safety_state.get("cooldown_reason"),
        cooldown_until=safety_state.get("cooldown_until"),
        cooldown_remaining_seconds=safety_state.get("cooldown_remaining_seconds"),
        blocked_start_count=((safety_state.get("counters") or {}).get("blocked_start_count")),
    )
    raise RunBlockedBySafetyPolicyError(
        code="scrape_cooldown_active",
        message="Scrape safety cooldown is active; run start is temporarily blocked.",
        safety_state=safety_state,
    )


async def run_preflight_guard(
    db_session: AsyncSession,
    source: ScholarSource,
    *,
    user_settings: Any,
    user_id: int,
    scholars: list[ScholarProfile],
) -> None:
    if not scholars:
        return
    result = await check_scholar_reachable(
        source,
        scholar_id=scholars[0].scholar_id,
    )
    if result.passed:
        return
    now_utc = datetime.now(UTC)
    safety_state, _ = run_safety_service.apply_run_safety_outcome(
        user_settings,
        run_id=0,
        blocked_failure_count=1,
        network_failure_count=0,
        blocked_failure_threshold=1,
        network_failure_threshold=1,
        blocked_cooldown_seconds=settings.ingestion_safety_cooldown_blocked_seconds,
        network_cooldown_seconds=settings.ingestion_safety_cooldown_network_seconds,
        now_utc=now_utc,
    )
    await db_session.commit()
    structured_log(
        logger,
        "warning",
        "ingestion.cooldown_entered_preflight",
        user_id=user_id,
        block_reason=result.block_reason,
        cooldown_until=safety_state.get("cooldown_until"),
    )
    raise RunBlockedBySafetyPolicyError(
        code="scrape_cooldown_active",
        message=f"Preflight detected Scholar block ({result.block_reason}). Cooldown activated.",
        safety_state=safety_state,
    )
