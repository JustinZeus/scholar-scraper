from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runtime_deps import get_scholar_source
from app.main import app
from app.services.scholar_source import FetchResult
from app.settings import settings
from tests.integration.helpers import insert_user, login_user


def _api_bootstrap_csrf_headers(client: TestClient) -> dict[str, str]:
    bootstrap_response = client.get("/api/v1/auth/csrf")
    assert bootstrap_response.status_code == 200
    payload = bootstrap_response.json()["data"]
    token = payload["csrf_token"]
    assert isinstance(token, str) and token
    return {"X-CSRF-Token": token}


def _api_csrf_headers(client: TestClient) -> dict[str, str]:
    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    body = me_response.json()
    token = body["data"]["csrf_token"]
    assert isinstance(token, str) and token
    return {"X-CSRF-Token": token}


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_me_requires_authentication() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "auth_required"
    assert payload["error"]["message"] == "Authentication required."
    assert "request_id" in payload["meta"]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_csrf_bootstrap_returns_token_for_anonymous_and_authenticated(
    db_session: AsyncSession,
) -> None:
    await insert_user(
        db_session,
        email="api-bootstrap@example.com",
        password="api-password",
    )
    client = TestClient(app)

    anonymous_response = client.get("/api/v1/auth/csrf")
    assert anonymous_response.status_code == 200
    anonymous_payload = anonymous_response.json()["data"]
    assert isinstance(anonymous_payload["csrf_token"], str)
    assert anonymous_payload["authenticated"] is False

    login_user(client, email="api-bootstrap@example.com", password="api-password")
    authenticated_response = client.get("/api/v1/auth/csrf")
    assert authenticated_response.status_code == 200
    authenticated_payload = authenticated_response.json()["data"]
    assert isinstance(authenticated_payload["csrf_token"], str)
    assert authenticated_payload["authenticated"] is True


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_me_returns_user_and_csrf_token(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-me@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-me@example.com", password="api-password")

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["authenticated"] is True
    assert payload["data"]["user"]["email"] == "api-me@example.com"
    assert isinstance(payload["data"]["csrf_token"], str)
    assert payload["meta"]["request_id"]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_login_and_change_password_flow(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-login@example.com",
        password="old-password",
    )
    client = TestClient(app)

    missing_csrf = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "old-password"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_missing"

    login_headers = _api_bootstrap_csrf_headers(client)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "old-password"},
        headers=login_headers,
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]
    assert login_payload["authenticated"] is True
    assert login_payload["user"]["email"] == "api-login@example.com"
    assert isinstance(login_payload["csrf_token"], str)

    bad_change_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "not-correct",
            "new_password": "new-password",
            "confirm_password": "new-password",
        },
        headers={"X-CSRF-Token": login_payload["csrf_token"]},
    )
    assert bad_change_response.status_code == 400
    assert bad_change_response.json()["error"]["code"] == "invalid_current_password"

    change_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "old-password",
            "new_password": "new-password",
            "confirm_password": "new-password",
        },
        headers={"X-CSRF-Token": login_payload["csrf_token"]},
    )
    assert change_response.status_code == 200
    assert change_response.json()["data"]["message"] == "Password updated successfully."

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": login_payload["csrf_token"]},
    )
    assert logout_response.status_code == 200

    relogin_headers = _api_bootstrap_csrf_headers(client)
    old_password_login = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "old-password"},
        headers=relogin_headers,
    )
    assert old_password_login.status_code == 401
    assert old_password_login.json()["error"]["code"] == "invalid_credentials"

    fresh_headers = _api_bootstrap_csrf_headers(client)
    new_password_login = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "new-password"},
        headers=fresh_headers,
    )
    assert new_password_login.status_code == 200
    assert new_password_login.json()["data"]["authenticated"] is True


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_user_management_endpoints(db_session: AsyncSession) -> None:
    admin_user_id = await insert_user(
        db_session,
        email="api-admin@example.com",
        password="admin-password",
        is_admin=True,
    )
    target_user_id = await insert_user(
        db_session,
        email="api-target@example.com",
        password="target-password",
        is_admin=False,
    )
    await insert_user(
        db_session,
        email="api-member@example.com",
        password="member-password",
        is_admin=False,
    )

    client = TestClient(app)
    login_user(client, email="api-admin@example.com", password="admin-password")
    headers = _api_csrf_headers(client)

    list_response = client.get("/api/v1/admin/users")
    assert list_response.status_code == 200
    users = list_response.json()["data"]["users"]
    assert any(item["email"] == "api-target@example.com" for item in users)

    create_response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "api-created@example.com",
            "password": "created-password",
            "is_admin": True,
        },
        headers=headers,
    )
    assert create_response.status_code == 201
    created_user = create_response.json()["data"]
    assert created_user["email"] == "api-created@example.com"
    created_user_id = int(created_user["id"])

    deactivate_response = client.patch(
        f"/api/v1/admin/users/{target_user_id}/active",
        json={"is_active": False},
        headers=headers,
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["data"]["is_active"] is False

    reactivate_response = client.patch(
        f"/api/v1/admin/users/{target_user_id}/active",
        json={"is_active": True},
        headers=headers,
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["data"]["is_active"] is True

    reset_response = client.post(
        f"/api/v1/admin/users/{target_user_id}/reset-password",
        json={"new_password": "target-password-updated"},
        headers=headers,
    )
    assert reset_response.status_code == 200
    assert "Password reset" in reset_response.json()["data"]["message"]

    self_deactivate = client.patch(
        f"/api/v1/admin/users/{admin_user_id}/active",
        json={"is_active": False},
        headers=headers,
    )
    assert self_deactivate.status_code == 400
    assert self_deactivate.json()["error"]["code"] == "cannot_deactivate_self"

    logout_response = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200

    target_headers = _api_bootstrap_csrf_headers(client)
    target_login = client.post(
        "/api/v1/auth/login",
        json={"email": "api-target@example.com", "password": "target-password-updated"},
        headers=target_headers,
    )
    assert target_login.status_code == 200

    non_admin_headers = {"X-CSRF-Token": target_login.json()["data"]["csrf_token"]}
    forbidden_response = client.get("/api/v1/admin/users")
    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["error"]["code"] == "forbidden"

    forbidden_create = client.post(
        "/api/v1/admin/users",
        json={
            "email": "should-not-work@example.com",
            "password": "password-123",
            "is_admin": False,
        },
        headers=non_admin_headers,
    )
    assert forbidden_create.status_code == 403

    created_exists = await db_session.execute(
        text("SELECT COUNT(*) FROM users WHERE id = :user_id"),
        {"user_id": created_user_id},
    )
    assert created_exists.scalar_one() == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_scholars_crud_flow(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-scholars@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-scholars@example.com", password="api-password")
    headers = _api_csrf_headers(client)

    missing_csrf = client.post(
        "/api/v1/scholars",
        json={"scholar_id": "abcDEF123456"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    create_response = client.post(
        "/api/v1/scholars",
        json={"scholar_id": "abcDEF123456"},
        headers=headers,
    )
    assert create_response.status_code == 201
    created = create_response.json()["data"]
    assert created["scholar_id"] == "abcDEF123456"
    scholar_profile_id = int(created["id"])

    list_response = client.get("/api/v1/scholars")
    assert list_response.status_code == 200
    scholars = list_response.json()["data"]["scholars"]
    assert any(int(item["id"]) == scholar_profile_id for item in scholars)

    toggle_response = client.patch(
        f"/api/v1/scholars/{scholar_profile_id}/toggle",
        headers=headers,
    )
    assert toggle_response.status_code == 200
    assert toggle_response.json()["data"]["is_enabled"] is False

    delete_response = client.delete(
        f"/api/v1/scholars/{scholar_profile_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["message"] == "Scholar deleted."


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_scholars_search_and_profile_image_management(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await insert_user(
        db_session,
        email="api-scholar-images@example.com",
        password="api-password",
    )

    class StubScholarSource:
        async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
            assert scholar_id == "abcDEF123456"
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                body=(
                    "<html><head>"
                    '<meta property="og:image" content="https://images.example.com/ada.png" />'
                    "</head><body>"
                    '<div id="gsc_prf_in">Ada Lovelace</div>'
                    "</body></html>"
                ),
                error=None,
            )

        async def fetch_author_search_html(self, query: str, *, start: int) -> FetchResult:
            assert query == "Ada Lovelace"
            assert start == 0
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
                body=(
                    '<div class="gsc_1usr">'
                    '<img src="/citations/images/avatar_scholar_256.png" />'
                    '<a class="gs_ai_name" href="/citations?hl=en&user=abcDEF123456">Ada Lovelace</a>'
                    '<div class="gs_ai_aff">Analytical Engine</div>'
                    '<div class="gs_ai_eml">Verified email at computing.example</div>'
                    '<div class="gs_ai_cby">Cited by 42</div>'
                    '<a class="gs_ai_one_int">Mathematics</a>'
                    "</div>"
                ),
                error=None,
            )

    previous_upload_dir = settings.scholar_image_upload_dir
    previous_upload_max_bytes = settings.scholar_image_upload_max_bytes
    app.dependency_overrides[get_scholar_source] = lambda: StubScholarSource()
    object.__setattr__(settings, "scholar_image_upload_dir", str(tmp_path / "scholar_images"))
    object.__setattr__(settings, "scholar_image_upload_max_bytes", 1_000_000)

    try:
        client = TestClient(app)
        login_user(client, email="api-scholar-images@example.com", password="api-password")
        headers = _api_csrf_headers(client)

        search_response = client.get("/api/v1/scholars/search", params={"query": "Ada Lovelace", "limit": 5})
        assert search_response.status_code == 200
        search_payload = search_response.json()["data"]
        assert search_payload["state"] == "ok"
        assert len(search_payload["candidates"]) == 1
        candidate = search_payload["candidates"][0]
        assert candidate["scholar_id"] == "abcDEF123456"
        assert candidate["profile_image_url"] == "https://scholar.google.com/citations/images/avatar_scholar_256.png"

        create_response = client.post(
            "/api/v1/scholars",
            json={
                "scholar_id": candidate["scholar_id"],
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()["data"]
        scholar_profile_id = int(created["id"])
        assert created["profile_image_source"] == "scraped"
        assert created["profile_image_url"] == "https://images.example.com/ada.png"

        set_url_response = client.put(
            f"/api/v1/scholars/{scholar_profile_id}/image/url",
            json={"image_url": "https://cdn.example.com/custom-avatar.png"},
            headers=headers,
        )
        assert set_url_response.status_code == 200
        set_url_data = set_url_response.json()["data"]
        assert set_url_data["profile_image_source"] == "override"
        assert set_url_data["profile_image_url"] == "https://cdn.example.com/custom-avatar.png"

        uploaded_bytes = b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01"
        upload_response = client.post(
            f"/api/v1/scholars/{scholar_profile_id}/image/upload",
            files={"image": ("avatar.png", uploaded_bytes, "image/png")},
            headers=headers,
        )
        assert upload_response.status_code == 200
        upload_data = upload_response.json()["data"]
        assert upload_data["profile_image_source"] == "upload"
        assert upload_data["profile_image_url"] == f"/api/v1/scholars/{scholar_profile_id}/image/upload"

        uploaded_image_response = client.get(f"/api/v1/scholars/{scholar_profile_id}/image/upload")
        assert uploaded_image_response.status_code == 200
        assert uploaded_image_response.headers["content-type"].startswith("image/png")
        assert uploaded_image_response.content == uploaded_bytes

        clear_response = client.delete(
            f"/api/v1/scholars/{scholar_profile_id}/image",
            headers=headers,
        )
        assert clear_response.status_code == 200
        clear_data = clear_response.json()["data"]
        assert clear_data["profile_image_source"] == "scraped"
        assert clear_data["profile_image_url"] == "https://images.example.com/ada.png"
    finally:
        app.dependency_overrides.pop(get_scholar_source, None)
        object.__setattr__(settings, "scholar_image_upload_dir", previous_upload_dir)
        object.__setattr__(
            settings,
            "scholar_image_upload_max_bytes",
            previous_upload_max_bytes,
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
        client = TestClient(app)
        login_user(client, email="api-skip-unchanged@example.com", password="api-password")
        headers = _api_csrf_headers(client)

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

        first_run_detail = client.get(f"/api/v1/runs/{first_run_id}")
        assert first_run_detail.status_code == 200
        first_results = first_run_detail.json()["data"]["scholar_results"]
        assert len(first_results) == 1
        assert first_results[0]["state_reason"] != "no_change_initial_page_signature"

        second_run_response = client.post(
            "/api/v1/runs/manual",
            headers={**headers, "Idempotency-Key": "skip-unchanged-run-002"},
        )
        assert second_run_response.status_code == 200
        second_run_id = int(second_run_response.json()["data"]["run_id"])

        second_run_detail = client.get(f"/api/v1/runs/{second_run_id}")
        assert second_run_detail.status_code == 200
        second_results = second_run_detail.json()["data"]["scholar_results"]
        assert len(second_results) == 1
        assert second_results[0]["state_reason"] == "no_change_initial_page_signature"
        assert second_results[0]["publication_count"] == 0
        assert second_results[0]["outcome"] == "success"
    finally:
        app.dependency_overrides.pop(get_scholar_source, None)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_settings_get_and_update(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-settings@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-settings@example.com", password="api-password")
    headers = _api_csrf_headers(client)

    get_response = client.get("/api/v1/settings")
    assert get_response.status_code == 200
    assert "request_delay_seconds" in get_response.json()["data"]

    update_response = client.put(
        "/api/v1/settings",
        json={
            "auto_run_enabled": True,
            "run_interval_minutes": 45,
            "request_delay_seconds": 6,
        },
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["auto_run_enabled"] is True
    assert updated["run_interval_minutes"] == 45
    assert updated["request_delay_seconds"] == 6


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
    headers = _api_csrf_headers(client)

    run_response = client.post(
        "/api/v1/runs/manual",
        headers={**headers, "Idempotency-Key": "manual-run-0001"},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()["data"]
    assert "run_id" in run_payload
    assert run_payload["status"] in {"success", "partial_failure", "failed"}
    assert run_payload["reused_existing_run"] is False
    assert run_payload["idempotency_key"] == "manual-run-0001"
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
    assert replay_response.status_code == 200
    replay_payload = replay_response.json()["data"]
    assert replay_payload["run_id"] == run_payload["run_id"]
    assert replay_payload["reused_existing_run"] is True

    runs_response = client.get("/api/v1/runs")
    assert runs_response.status_code == 200
    assert len(runs_response.json()["data"]["runs"]) >= 1

    run_detail_response = client.get(f"/api/v1/runs/{run_id}")
    assert run_detail_response.status_code == 200
    detail_payload = run_detail_response.json()["data"]
    assert "summary" in detail_payload
    assert isinstance(detail_payload["scholar_results"], list)

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
    assert any(
        int(item["id"]) == queue_item_id
        for item in queue_list_response.json()["data"]["queue_items"]
    )

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
async def test_api_publications_list_and_mark_read(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs@example.com",
        password="api-password",
    )

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
            "display_name": "Publication Owner",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    publication_a = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 10)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{user_id:064x}",
            "title_raw": "Paper A",
            "title_normalized": "paper a",
        },
    )
    publication_a_id = int(publication_a.scalar_one())

    publication_b = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 4)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1):064x}",
            "title_raw": "Paper B",
            "title_normalized": "paper b",
        },
    )
    publication_b_id = int(publication_b.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read)
            VALUES
              (:scholar_profile_id, :publication_a_id, false),
              (:scholar_profile_id, :publication_b_id, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_a_id": publication_a_id,
            "publication_b_id": publication_b_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs@example.com", password="api-password")
    headers = _api_csrf_headers(client)

    list_response = client.get("/api/v1/publications?mode=all")
    assert list_response.status_code == 200
    data = list_response.json()["data"]
    assert data["mode"] == "all"
    assert isinstance(data["publications"], list)
    assert len(data["publications"]) == 2

    mark_selected_response = client.post(
        "/api/v1/publications/mark-read",
        json={
            "selections": [
                {
                    "scholar_profile_id": scholar_profile_id,
                    "publication_id": publication_a_id,
                }
            ]
        },
        headers=headers,
    )
    assert mark_selected_response.status_code == 200
    assert mark_selected_response.json()["data"]["requested_count"] == 1
    assert mark_selected_response.json()["data"]["updated_count"] == 1

    read_state = await db_session.execute(
        text(
            """
            SELECT publication_id, is_read
            FROM scholar_publications
            WHERE scholar_profile_id = :scholar_profile_id
            ORDER BY publication_id
            """
        ),
        {"scholar_profile_id": scholar_profile_id},
    )
    states = {int(row[0]): bool(row[1]) for row in read_state.all()}
    assert states[publication_a_id] is True
    assert states[publication_b_id] is False

    mark_response = client.post("/api/v1/publications/mark-all-read", headers=headers)
    assert mark_response.status_code == 200
    assert mark_response.json()["data"]["updated_count"] == 1
