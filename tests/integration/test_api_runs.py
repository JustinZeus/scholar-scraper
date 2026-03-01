from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runtime_deps import get_scholar_source
from app.main import app
from app.services.scholar.source import FetchResult
from app.settings import settings
from tests.integration.helpers import (
    api_csrf_headers,
    assert_safety_state_contract,
    insert_user,
    login_user,
    regression_fixture,
    wait_for_run_complete,
)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_manual_run_skips_unchanged_initial_page_for_scholar(
    db_session: AsyncSession,
) -> None:
    await insert_user(
        db_session,
        email="api-skip-unchanged@example.com",
        password="api-password",
    )

    profile_html = """
    <html>
      <head>
        <meta property="og:image" content="https://images.example.com/skip.png" />
      </head>
      <body>
        <div id="gsc_prf_in">Skip Candidate</div>
        <span id="gsc_a_nn">Articles 1-1</span>
        <table>
          <tbody id="gsc_a_b">
            <tr class="gsc_a_tr">
              <td class="gsc_a_t">
                <a class="gsc_a_at" href="/citations?view_op=view_citation&citation_for_view=abcDEF123456:xyz123">Stable Paper</a>
                <div class="gs_gray">A Author</div>
                <div class="gs_gray">Stable Venue</div>
              </td>
              <td class="gsc_a_c"><a class="gsc_a_ac">5</a></td>
              <td class="gsc_a_y"><span class="gsc_a_h">2024</span></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    class StubScholarSource:
        async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
            assert scholar_id == "abcDEF123456"
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                body=profile_html,
                error=None,
            )

        async def fetch_profile_page_html(
            self,
            scholar_id: str,
            *,
            cstart: int,
            pagesize: int,
        ) -> FetchResult:
            assert scholar_id == "abcDEF123456"
            assert cstart == 0
            assert pagesize == settings.ingestion_page_size
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                body=profile_html,
                error=None,
            )

    app.dependency_overrides[get_scholar_source] = lambda: StubScholarSource()
    try:
        with TestClient(app) as client:
            login_user(client, email="api-skip-unchanged@example.com", password="api-password")
            headers = api_csrf_headers(client)

            create_response = client.post(
                "/api/v1/scholars",
                json={"scholar_id": "abcDEF123456"},
                headers=headers,
            )
            assert create_response.status_code == 201

            first_run_response = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "skip-unchanged-run-001"},
            )
            assert first_run_response.status_code == 200
            first_run_id = int(first_run_response.json()["data"]["run_id"])

            first_detail_data = await wait_for_run_complete(client, first_run_id)
            first_results = first_detail_data["scholar_results"]
            assert len(first_results) == 1
            assert first_results[0]["state_reason"] != "no_change_initial_page_signature"

            second_run_response = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "skip-unchanged-run-002"},
            )
            assert second_run_response.status_code == 200
            second_run_id = int(second_run_response.json()["data"]["run_id"])

            second_detail_data = await wait_for_run_complete(client, second_run_id)
            second_results = second_detail_data["scholar_results"]
            assert len(second_results) == 1
            assert second_results[0]["state_reason"] == "no_change_initial_page_signature"
            assert second_results[0]["publication_count"] == 0
            assert second_results[0]["outcome"] == "success"
    finally:
        app.dependency_overrides.pop(get_scholar_source, None)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_runs_manual_and_queue_actions(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-runs@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-runs@example.com", password="api-password")
    headers = api_csrf_headers(client)

    run_response = client.post(
        "/api/v1/runs/manual",
        headers={**headers, "Idempotency-Key": "manual-run-0001"},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()["data"]
    assert "run_id" in run_payload
    assert run_payload["status"] in {"running", "resolving", "success", "partial_failure", "failed"}
    assert run_payload["reused_existing_run"] is False
    assert run_payload["idempotency_key"] == "manual-run-0001"
    assert_safety_state_contract(run_payload["safety_state"])
    run_id = int(run_payload["run_id"])

    stored_key = await db_session.execute(
        text("SELECT idempotency_key FROM crawl_runs WHERE id = :run_id"),
        {"run_id": run_id},
    )
    assert stored_key.scalar_one() == "manual-run-0001"

    replay_response = client.post(
        "/api/v1/runs/manual",
        headers={**headers, "Idempotency-Key": "manual-run-0001"},
    )
    assert replay_response.status_code in {200, 409}
    if replay_response.status_code == 200:
        replay_payload = replay_response.json()["data"]
        assert replay_payload["run_id"] == run_payload["run_id"]
        assert replay_payload["reused_existing_run"] is True
        assert_safety_state_contract(replay_payload["safety_state"])
    else:
        replay_error = replay_response.json()["error"]
        assert replay_error["code"] == "run_in_progress"

    runs_response = client.get("/api/v1/runs")
    assert runs_response.status_code == 200
    assert len(runs_response.json()["data"]["runs"]) >= 1
    assert_safety_state_contract(runs_response.json()["data"]["safety_state"])

    run_detail_response = client.get(f"/api/v1/runs/{run_id}")
    assert run_detail_response.status_code == 200
    detail_payload = run_detail_response.json()["data"]
    assert "summary" in detail_payload
    assert isinstance(detail_payload["scholar_results"], list)
    assert_safety_state_contract(detail_payload["safety_state"])

    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Queue Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    queue_result = await db_session.execute(
        text(
            """
            INSERT INTO ingestion_queue_items (
                user_id,
                scholar_profile_id,
                resume_cstart,
                reason,
                status,
                attempt_count,
                next_attempt_dt,
                dropped_reason,
                dropped_at
            )
            VALUES (
                :user_id,
                :scholar_profile_id,
                7,
                'dropped',
                'dropped',
                2,
                NOW(),
                'manual_drop',
                NOW()
            )
            RETURNING id
            """
        ),
        {"user_id": user_id, "scholar_profile_id": scholar_profile_id},
    )
    queue_item_id = int(queue_result.scalar_one())
    await db_session.commit()

    queue_list_response = client.get("/api/v1/runs/queue/items")
    assert queue_list_response.status_code == 200
    assert any(int(item["id"]) == queue_item_id for item in queue_list_response.json()["data"]["queue_items"])

    retry_response = client.post(f"/api/v1/runs/queue/{queue_item_id}/retry", headers=headers)
    assert retry_response.status_code == 200
    assert retry_response.json()["data"]["status"] == "queued"

    retry_again_response = client.post(
        f"/api/v1/runs/queue/{queue_item_id}/retry",
        headers=headers,
    )
    assert retry_again_response.status_code == 409
    assert retry_again_response.json()["error"]["code"] == "queue_item_already_queued"

    drop_response = client.post(f"/api/v1/runs/queue/{queue_item_id}/drop", headers=headers)
    assert drop_response.status_code == 200
    assert drop_response.json()["data"]["status"] == "dropped"

    clear_response = client.request(
        "DELETE",
        f"/api/v1/runs/queue/{queue_item_id}",
        headers=headers,
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["data"]["status"] == "cleared"
    assert clear_response.json()["data"]["message"] == "Queue item cleared."


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_manual_run_can_be_disabled_by_policy(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-runs-policy@example.com",
        password="api-password",
    )
    client = TestClient(app)
    login_user(client, email="api-runs-policy@example.com", password="api-password")
    headers = api_csrf_headers(client)

    previous_manual_allowed = settings.ingestion_manual_run_allowed
    object.__setattr__(settings, "ingestion_manual_run_allowed", False)
    try:
        response = client.post("/api/v1/runs/manual", headers=headers)
        assert response.status_code == 403
        payload = response.json()
        assert payload["error"]["code"] == "manual_runs_disabled"
        assert payload["error"]["details"]["policy"]["manual_run_allowed"] is False
        assert payload["error"]["details"]["safety_state"]["cooldown_active"] is False
    finally:
        object.__setattr__(settings, "ingestion_manual_run_allowed", previous_manual_allowed)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_manual_run_enforces_scrape_safety_cooldown(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-runs-safety@example.com",
        password="api-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "A1B2C3D4E5F6",
            "display_name": "Safety Probe",
        },
    )
    await db_session.commit()

    blocked_fixture = regression_fixture("profile_AAAAAAAAAAAA.html")

    class BlockedScholarSource:
        async def fetch_profile_page_html(
            self,
            scholar_id: str,
            *,
            cstart: int,
            pagesize: int,
        ) -> FetchResult:
            _ = (scholar_id, cstart, pagesize)
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=A1B2C3D4E5F6",
                status_code=200,
                final_url=(
                    "https://accounts.google.com/v3/signin/identifier"
                    "?continue=https%3A%2F%2Fscholar.google.com%2Fcitations"
                ),
                body=blocked_fixture,
                error=None,
            )

        async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
            _ = scholar_id
            return await self.fetch_profile_page_html(
                "A1B2C3D4E5F6",
                cstart=0,
                pagesize=settings.ingestion_page_size,
            )

    app.dependency_overrides[get_scholar_source] = lambda: BlockedScholarSource()

    previous_blocked_cooldown_seconds = settings.ingestion_safety_cooldown_blocked_seconds
    object.__setattr__(settings, "ingestion_safety_cooldown_blocked_seconds", 600)

    try:
        with TestClient(app) as client:
            login_user(client, email="api-runs-safety@example.com", password="api-password")
            headers = api_csrf_headers(client)

            preflight_response = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "safety-cooldown-run-1"},
            )
            assert preflight_response.status_code == 429
            preflight_payload = preflight_response.json()
            assert preflight_payload["error"]["code"] == "scrape_cooldown_active"
            preflight_state = preflight_payload["error"]["details"]["safety_state"]
            assert_safety_state_contract(preflight_state)
            assert preflight_state["cooldown_active"] is True

            settings_response = client.get("/api/v1/settings")
            assert settings_response.status_code == 200
            safety_state = settings_response.json()["data"]["safety_state"]
            assert_safety_state_contract(safety_state)
            assert safety_state["cooldown_active"] is True
            assert safety_state["cooldown_reason"] == "blocked_failure_threshold_exceeded"
            assert int(safety_state["cooldown_remaining_seconds"]) > 0
            assert int(safety_state["counters"]["cooldown_entry_count"]) >= 1

            blocked_start_response = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "safety-cooldown-run-2"},
            )
            assert blocked_start_response.status_code == 429
            blocked_payload = blocked_start_response.json()
            assert blocked_payload["error"]["code"] == "scrape_cooldown_active"
            blocked_state = blocked_payload["error"]["details"]["safety_state"]
            assert_safety_state_contract(blocked_state)
            assert blocked_state["cooldown_active"] is True
            assert blocked_state["cooldown_reason"] == "blocked_failure_threshold_exceeded"
            assert int(blocked_state["counters"]["blocked_start_count"]) >= 1

            runs_response = client.get("/api/v1/runs")
            assert runs_response.status_code == 200
            assert_safety_state_contract(runs_response.json()["data"]["safety_state"])
            assert runs_response.json()["data"]["safety_state"]["cooldown_active"] is True
    finally:
        object.__setattr__(settings, "ingestion_safety_cooldown_blocked_seconds", previous_blocked_cooldown_seconds)
        app.dependency_overrides.pop(get_scholar_source, None)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_manual_run_enforces_network_failure_safety_cooldown(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-runs-safety-network@example.com",
        password="api-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "NNN111NNN111",
            "display_name": "Network Safety Probe",
        },
    )
    await db_session.commit()

    class NetworkFailureScholarSource:
        async def fetch_profile_page_html(
            self,
            scholar_id: str,
            *,
            cstart: int,
            pagesize: int,
        ) -> FetchResult:
            _ = (scholar_id, cstart, pagesize)
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=NNN111NNN111",
                status_code=None,
                final_url=None,
                body="",
                error="timed out",
            )

        async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
            _ = scholar_id
            return await self.fetch_profile_page_html(
                "NNN111NNN111",
                cstart=0,
                pagesize=settings.ingestion_page_size,
            )

    app.dependency_overrides[get_scholar_source] = lambda: NetworkFailureScholarSource()

    previous_network_threshold = settings.ingestion_alert_network_failure_threshold
    previous_network_cooldown_seconds = settings.ingestion_safety_cooldown_network_seconds
    previous_network_retries = settings.ingestion_network_error_retries
    previous_retry_backoff = settings.ingestion_retry_backoff_seconds
    object.__setattr__(settings, "ingestion_alert_network_failure_threshold", 1)
    object.__setattr__(settings, "ingestion_safety_cooldown_network_seconds", 600)
    object.__setattr__(settings, "ingestion_network_error_retries", 0)
    object.__setattr__(settings, "ingestion_retry_backoff_seconds", 0.0)

    try:
        with TestClient(app) as client:
            login_user(client, email="api-runs-safety-network@example.com", password="api-password")
            headers = api_csrf_headers(client)

            first_run_response = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "safety-network-cooldown-run-1"},
            )
            assert first_run_response.status_code == 200
            first_run_id = int(first_run_response.json()["data"]["run_id"])
            await wait_for_run_complete(client, first_run_id)

            settings_response = client.get("/api/v1/settings")
            assert settings_response.status_code == 200
            safety_state = settings_response.json()["data"]["safety_state"]
            assert_safety_state_contract(safety_state)
            assert safety_state["cooldown_active"] is True
            assert safety_state["cooldown_reason"] == "network_failure_threshold_exceeded"
            assert int(safety_state["cooldown_remaining_seconds"]) > 0
            assert int(safety_state["counters"]["last_network_failure_count"]) >= 1

            blocked_start_response = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "safety-network-cooldown-run-2"},
            )
            assert blocked_start_response.status_code == 429
            blocked_payload = blocked_start_response.json()
            assert blocked_payload["error"]["code"] == "scrape_cooldown_active"
            blocked_state = blocked_payload["error"]["details"]["safety_state"]
            assert_safety_state_contract(blocked_state)
            assert blocked_state["cooldown_active"] is True
            assert blocked_state["cooldown_reason"] == "network_failure_threshold_exceeded"
            assert int(blocked_state["counters"]["blocked_start_count"]) >= 1
    finally:
        object.__setattr__(settings, "ingestion_alert_network_failure_threshold", previous_network_threshold)
        object.__setattr__(settings, "ingestion_safety_cooldown_network_seconds", previous_network_cooldown_seconds)
        object.__setattr__(settings, "ingestion_network_error_retries", previous_network_retries)
        object.__setattr__(settings, "ingestion_retry_backoff_seconds", previous_retry_backoff)
        app.dependency_overrides.pop(get_scholar_source, None)
