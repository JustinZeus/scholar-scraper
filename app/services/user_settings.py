from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserSetting


class UserSettingsServiceError(ValueError):
    """Raised for expected settings-validation failures."""


NAV_PAGE_DASHBOARD = "dashboard"
NAV_PAGE_SCHOLARS = "scholars"
NAV_PAGE_PUBLICATIONS = "publications"
NAV_PAGE_SETTINGS = "settings"
NAV_PAGE_STYLE_GUIDE = "style-guide"
NAV_PAGE_RUNS = "runs"
NAV_PAGE_USERS = "users"

ALLOWED_NAV_PAGES = (
    NAV_PAGE_DASHBOARD,
    NAV_PAGE_SCHOLARS,
    NAV_PAGE_PUBLICATIONS,
    NAV_PAGE_SETTINGS,
    NAV_PAGE_STYLE_GUIDE,
    NAV_PAGE_RUNS,
    NAV_PAGE_USERS,
)
REQUIRED_NAV_PAGES = (
    NAV_PAGE_DASHBOARD,
    NAV_PAGE_SCHOLARS,
    NAV_PAGE_SETTINGS,
)
DEFAULT_NAV_VISIBLE_PAGES = list(ALLOWED_NAV_PAGES)


def parse_run_interval_minutes(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise UserSettingsServiceError("Check interval must be a whole number.") from exc
    if parsed < 15:
        raise UserSettingsServiceError("Check interval must be at least 15 minutes.")
    return parsed


def parse_request_delay_seconds(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise UserSettingsServiceError("Request delay must be a whole number.") from exc
    if parsed < 2:
        raise UserSettingsServiceError("Request delay must be at least 2 seconds.")
    return parsed


def parse_nav_visible_pages(value: object) -> list[str]:
    if not isinstance(value, list):
        raise UserSettingsServiceError("Navigation visibility must be a list of page ids.")

    deduped: list[str] = []
    seen: set[str] = set()

    for raw_page in value:
        if not isinstance(raw_page, str):
            raise UserSettingsServiceError("Navigation visibility entries must be strings.")

        page_id = raw_page.strip()
        if page_id not in ALLOWED_NAV_PAGES:
            raise UserSettingsServiceError(f"Unsupported navigation page id: {page_id}")

        if page_id in seen:
            continue

        seen.add(page_id)
        deduped.append(page_id)

    missing_required = [page for page in REQUIRED_NAV_PAGES if page not in seen]
    if missing_required:
        raise UserSettingsServiceError(
            "Dashboard, Scholars, and Settings must remain visible."
        )

    return deduped


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
    nav_visible_pages: list[str],
) -> UserSetting:
    settings.auto_run_enabled = auto_run_enabled
    settings.run_interval_minutes = run_interval_minutes
    settings.request_delay_seconds = request_delay_seconds
    settings.nav_visible_pages = nav_visible_pages
    await db_session.commit()
    await db_session.refresh(settings)
    return settings
