from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserSetting


class UserSettingsServiceError(ValueError):
    """Raised for expected settings-validation failures."""


def parse_run_interval_minutes(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise UserSettingsServiceError("Run interval must be a whole number.") from exc
    if parsed < 15:
        raise UserSettingsServiceError("Run interval must be at least 15 minutes.")
    return parsed


def parse_request_delay_seconds(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise UserSettingsServiceError("Request delay must be a whole number.") from exc
    if parsed < 1:
        raise UserSettingsServiceError("Request delay must be at least 1 second.")
    return parsed


async def get_or_create_settings(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> UserSetting:
    result = await db_session.execute(
        select(UserSetting).where(UserSetting.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings

    settings = UserSetting(user_id=user_id)
    db_session.add(settings)
    await db_session.commit()
    await db_session.refresh(settings)
    return settings


async def update_settings(
    db_session: AsyncSession,
    *,
    settings: UserSetting,
    auto_run_enabled: bool,
    run_interval_minutes: int,
    request_delay_seconds: int,
) -> UserSetting:
    settings.auto_run_enabled = auto_run_enabled
    settings.run_interval_minutes = run_interval_minutes
    settings.request_delay_seconds = request_delay_seconds
    await db_session.commit()
    await db_session.refresh(settings)
    return settings

