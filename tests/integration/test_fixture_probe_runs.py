from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RunStatus, RunTriggerType
from app.services.domains.ingestion.application import ScholarIngestionService
from app.services.domains.scholar.source import FetchResult
from tests.integration.helpers import insert_user

REGRESSION_FIXTURE_DIR = Path("tests/fixtures/scholar/regression")


def _fixture(name: str) -> str:
    return (REGRESSION_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _profile_fetch(*, scholar_id: str, body: str) -> FetchResult:
    return FetchResult(
        requested_url=f"https://scholar.google.com/citations?hl=en&user={scholar_id}",
        status_code=200,
        final_url=f"https://scholar.google.com/citations?hl=en&user={scholar_id}",
        body=body,
        error=None,
    )


def _blocked_fetch(*, scholar_id: str, body: str) -> FetchResult:
    return FetchResult(
        requested_url=f"https://scholar.google.com/citations?hl=en&user={scholar_id}",
        status_code=200,
        final_url=(
            "https://accounts.google.com/v3/signin/identifier"
            "?continue=https%3A%2F%2Fscholar.google.com%2Fcitations"
        ),
        body=body,
        error=None,
    )


def _network_timeout_fetch(*, scholar_id: str) -> FetchResult:
    return FetchResult(
        requested_url=f"https://scholar.google.com/citations?hl=en&user={scholar_id}",
        status_code=None,
        final_url=None,
        body="",
        error="timed out",
    )


class FixtureScholarSource:
    def __init__(self, responses: dict[tuple[str, int], list[FetchResult]]) -> None:
        self._responses = responses
        self._calls: defaultdict[tuple[str, int], int] = defaultdict(int)

    async def fetch_profile_page_html(
        self,
        scholar_id: str,
        *,
        cstart: int,
        pagesize: int,
    ) -> FetchResult:
        _ = pagesize
        key = (scholar_id, int(cstart))
        fetches = self._responses.get(key)
        if not fetches:
            return _network_timeout_fetch(scholar_id=scholar_id)

        call_index = self._calls[key]
        self._calls[key] += 1
        return fetches[min(call_index, len(fetches) - 1)]

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        return await self.fetch_profile_page_html(scholar_id, cstart=0, pagesize=100)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_fixture_probe_run_emits_failure_and_retry_summary_metrics(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="fixture-probe@example.com",
        password="fixture-probe-password",
    )

    scholar_ids = {
        "ok": "abcDEF123456",
        "blocked": "A1B2C3D4E5F6",
        "retry": "RSTUVWX12345",
    }

    for label in ("ok", "blocked", "retry"):
        await db_session.execute(
            text(
                """
                INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
                VALUES (:user_id, :scholar_id, :display_name, true)
                """
            ),
            {
                "user_id": user_id,
                "scholar_id": scholar_ids[label],
                "display_name": f"fixture-{label}",
            },
        )
    await db_session.commit()

    source = FixtureScholarSource(
        {
            (scholar_ids["ok"], 0): [
                _profile_fetch(
                    scholar_id=scholar_ids["ok"],
                    body=_fixture("profile_P1RwlvoAAAAJ.html"),
                )
            ],
            (scholar_ids["blocked"], 0): [
                _blocked_fetch(
                    scholar_id=scholar_ids["blocked"],
                    body=_fixture("profile_AAAAAAAAAAAA.html"),
                )
            ],
            (scholar_ids["retry"], 0): [
                _network_timeout_fetch(scholar_id=scholar_ids["retry"]),
                _profile_fetch(
                    scholar_id=scholar_ids["retry"],
                    body=_fixture("profile_LZ5D_p4AAAAJ.html"),
                ),
            ],
        }
    )
    ingestion = ScholarIngestionService(source=source)

    summary = await ingestion.run_for_user(
        db_session,
        user_id=user_id,
        trigger_type=RunTriggerType.MANUAL,
        request_delay_seconds=0,
        network_error_retries=1,
        retry_backoff_seconds=0.0,
        max_pages_per_scholar=1,
        page_size=100,
        auto_queue_continuations=False,
        alert_blocked_failure_threshold=1,
        alert_network_failure_threshold=1,
        alert_retry_scheduled_threshold=1,
    )

    assert summary.status == RunStatus.PARTIAL_FAILURE
    assert summary.scholar_count == 3
    assert summary.succeeded_count == 2
    assert summary.failed_count == 1
    assert summary.partial_count == 0

    run_result = await db_session.execute(
        text("SELECT error_log FROM crawl_runs WHERE id = :run_id"),
        {"run_id": summary.crawl_run_id},
    )
    error_log = run_result.scalar_one()
    run_summary = error_log["summary"]

    assert run_summary["failed_state_counts"]["blocked_or_captcha"] == 1
    assert run_summary["failed_reason_counts"]["blocked_accounts_redirect"] == 1
    assert run_summary["scrape_failure_counts"]["blocked_or_captcha"] == 1

    assert run_summary["retry_counts"]["retries_scheduled_count"] == 1
    assert run_summary["retry_counts"]["scholars_with_retries_count"] == 1
    assert run_summary["retry_counts"]["retry_exhausted_count"] == 0

    assert run_summary["alert_thresholds"]["blocked_failure_threshold"] == 1
    assert run_summary["alert_thresholds"]["network_failure_threshold"] == 1
    assert run_summary["alert_thresholds"]["retry_scheduled_threshold"] == 1

    assert run_summary["alert_flags"]["blocked_failure_threshold_exceeded"] is True
    assert run_summary["alert_flags"]["network_failure_threshold_exceeded"] is False
    assert run_summary["alert_flags"]["retry_scheduled_threshold_exceeded"] is True
