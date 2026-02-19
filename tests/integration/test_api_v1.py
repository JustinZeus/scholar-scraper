from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runtime_deps import get_scholar_source
from app.main import app
from app.services import user_settings as user_settings_service
from app.services.scholar_source import FetchResult
from app.settings import settings
from tests.integration.helpers import insert_user, login_user

REGRESSION_FIXTURE_DIR = Path("tests/fixtures/scholar/regression")
SAFETY_STATE_KEYS = {
    "cooldown_active",
    "cooldown_reason",
    "cooldown_reason_label",
    "cooldown_until",
    "cooldown_remaining_seconds",
    "recommended_action",
    "counters",
}
SAFETY_COUNTER_KEYS = {
    "consecutive_blocked_runs",
    "consecutive_network_runs",
    "cooldown_entry_count",
    "blocked_start_count",
    "last_blocked_failure_count",
    "last_network_failure_count",
    "last_evaluated_run_id",
}


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


def _regression_fixture(name: str) -> str:
    return (REGRESSION_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _assert_safety_state_contract(payload: dict[str, object]) -> None:
    assert set(payload.keys()) == SAFETY_STATE_KEYS
    counters = payload["counters"]
    assert isinstance(counters, dict)
    assert set(counters.keys()) == SAFETY_COUNTER_KEYS


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
async def test_api_scholar_import_export_round_trip(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-import-export@example.com",
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
            "display_name": "Existing Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 1)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 500):064x}",
            "title_raw": "Existing Publication",
            "title_normalized": "existingpublication",
        },
    )
    publication_id = int(publication_result.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read)
            VALUES (:scholar_profile_id, :publication_id, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_id": publication_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-import-export@example.com", password="api-password")
    headers = _api_csrf_headers(client)

    export_response = client.get("/api/v1/scholars/export")
    assert export_response.status_code == 200
    export_payload = export_response.json()["data"]
    assert export_payload["schema_version"] == 1
    assert len(export_payload["scholars"]) == 1
    assert len(export_payload["publications"]) == 1

    import_response = client.post(
        "/api/v1/scholars/import",
        json={
            "schema_version": 1,
            "scholars": [
                {
                    "scholar_id": "abcDEF123456",
                    "display_name": "Updated Scholar",
                    "is_enabled": False,
                    "profile_image_override_url": "https://cdn.example.com/avatar.png",
                },
                {
                    "scholar_id": "zzzYYY111222",
                    "display_name": "Imported Scholar",
                    "is_enabled": True,
                    "profile_image_override_url": None,
                },
            ],
            "publications": [
                {
                    "scholar_id": "abcDEF123456",
                    "title": "Existing Publication",
                    "year": 2024,
                    "citation_count": 8,
                    "author_text": "A. Author",
                    "venue_text": "Test Venue",
                    "pub_url": "https://example.org/existing",
                    "pdf_url": "https://example.org/existing.pdf",
                    "is_read": True,
                },
                {
                    "scholar_id": "zzzYYY111222",
                    "title": "Imported Publication",
                    "year": 2025,
                    "citation_count": 2,
                    "author_text": "B. Author",
                    "venue_text": "Another Venue",
                    "pub_url": "https://example.org/imported",
                    "pdf_url": "https://example.org/imported.pdf",
                    "is_read": False,
                },
            ],
        },
        headers=headers,
    )
    assert import_response.status_code == 200
    import_data = import_response.json()["data"]
    assert int(import_data["scholars_created"]) == 1
    assert int(import_data["scholars_updated"]) >= 1
    assert int(import_data["publications_created"]) == 1
    assert int(import_data["links_created"]) == 1

    updated_scholar_result = await db_session.execute(
        text(
            """
            SELECT display_name, is_enabled, profile_image_override_url
            FROM scholar_profiles
            WHERE user_id = :user_id AND scholar_id = :scholar_id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
        },
    )
    updated_scholar = updated_scholar_result.one()
    assert updated_scholar[0] == "Updated Scholar"
    assert updated_scholar[1] is False
    assert updated_scholar[2] == "https://cdn.example.com/avatar.png"

    imported_pub_result = await db_session.execute(
        text(
            """
            SELECT p.title_raw, p.pdf_url
            FROM publications p
            WHERE p.title_raw = :title
            """
        ),
        {"title": "Imported Publication"},
    )
    imported_pub = imported_pub_result.one()
    assert imported_pub[0] == "Imported Publication"
    assert imported_pub[1] == "https://example.org/imported.pdf"

    updated_link_result = await db_session.execute(
        text(
            """
            SELECT sp.is_read
            FROM scholar_publications sp
            JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
            JOIN publications p ON p.id = sp.publication_id
            WHERE s.user_id = :user_id
              AND s.scholar_id = :scholar_id
              AND p.title_raw = :title
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "title": "Existing Publication",
        },
    )
    assert bool(updated_link_result.scalar_one()) is True


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
    settings_payload = get_response.json()["data"]
    assert "request_delay_seconds" in settings_payload
    assert "nav_visible_pages" in settings_payload
    assert settings_payload["policy"]["min_run_interval_minutes"] == user_settings_service.resolve_run_interval_minimum(
        settings.ingestion_min_run_interval_minutes
    )
    assert settings_payload["policy"]["min_request_delay_seconds"] == user_settings_service.resolve_request_delay_minimum(
        settings.ingestion_min_request_delay_seconds
    )
    assert settings_payload["policy"]["automation_allowed"] is settings.ingestion_automation_allowed
    assert settings_payload["policy"]["manual_run_allowed"] is settings.ingestion_manual_run_allowed
    assert settings_payload["policy"]["blocked_failure_threshold"] == max(
        1,
        int(settings.ingestion_alert_blocked_failure_threshold),
    )
    assert settings_payload["policy"]["network_failure_threshold"] == max(
        1,
        int(settings.ingestion_alert_network_failure_threshold),
    )
    assert settings_payload["policy"]["cooldown_blocked_seconds"] == max(
        60,
        int(settings.ingestion_safety_cooldown_blocked_seconds),
    )
    assert settings_payload["policy"]["cooldown_network_seconds"] == max(
        60,
        int(settings.ingestion_safety_cooldown_network_seconds),
    )
    _assert_safety_state_contract(settings_payload["safety_state"])
    assert settings_payload["safety_state"]["cooldown_active"] is False

    update_response = client.put(
        "/api/v1/settings",
        json={
            "auto_run_enabled": True,
            "run_interval_minutes": 45,
            "request_delay_seconds": 6,
            "nav_visible_pages": ["dashboard", "scholars", "publications", "settings", "runs"],
        },
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["auto_run_enabled"] is True
    assert updated["run_interval_minutes"] == 45
    assert updated["request_delay_seconds"] == 6
    assert updated["nav_visible_pages"] == [
        "dashboard",
        "scholars",
        "publications",
        "settings",
        "runs",
    ]
    assert "policy" in updated
    _assert_safety_state_contract(updated["safety_state"])


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_settings_enforce_env_minimums(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-settings-policy@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-settings-policy@example.com", password="api-password")
    headers = _api_csrf_headers(client)

    previous_min_interval = settings.ingestion_min_run_interval_minutes
    previous_min_delay = settings.ingestion_min_request_delay_seconds
    object.__setattr__(settings, "ingestion_min_run_interval_minutes", 30)
    object.__setattr__(settings, "ingestion_min_request_delay_seconds", 8)
    try:
        interval_response = client.put(
            "/api/v1/settings",
            json={
                "auto_run_enabled": True,
                "run_interval_minutes": 29,
                "request_delay_seconds": 9,
                "nav_visible_pages": ["dashboard", "scholars", "settings"],
            },
            headers=headers,
        )
        assert interval_response.status_code == 400
        assert interval_response.json()["error"]["code"] == "invalid_settings"
        assert interval_response.json()["error"]["message"] == "Check interval must be at least 30 minutes."

        delay_response = client.put(
            "/api/v1/settings",
            json={
                "auto_run_enabled": True,
                "run_interval_minutes": 30,
                "request_delay_seconds": 7,
                "nav_visible_pages": ["dashboard", "scholars", "settings"],
            },
            headers=headers,
        )
        assert delay_response.status_code == 400
        assert delay_response.json()["error"]["code"] == "invalid_settings"
        assert delay_response.json()["error"]["message"] == "Request delay must be at least 8 seconds."
    finally:
        object.__setattr__(settings, "ingestion_min_run_interval_minutes", previous_min_interval)
        object.__setattr__(settings, "ingestion_min_request_delay_seconds", previous_min_delay)


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
    _assert_safety_state_contract(run_payload["safety_state"])
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
    _assert_safety_state_contract(replay_payload["safety_state"])

    runs_response = client.get("/api/v1/runs")
    assert runs_response.status_code == 200
    assert len(runs_response.json()["data"]["runs"]) >= 1
    _assert_safety_state_contract(runs_response.json()["data"]["safety_state"])

    run_detail_response = client.get(f"/api/v1/runs/{run_id}")
    assert run_detail_response.status_code == 200
    detail_payload = run_detail_response.json()["data"]
    assert "summary" in detail_payload
    assert isinstance(detail_payload["scholar_results"], list)
    _assert_safety_state_contract(detail_payload["safety_state"])

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
async def test_api_manual_run_can_be_disabled_by_policy(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-runs-policy@example.com",
        password="api-password",
    )
    client = TestClient(app)
    login_user(client, email="api-runs-policy@example.com", password="api-password")
    headers = _api_csrf_headers(client)

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

    blocked_fixture = _regression_fixture("profile_AAAAAAAAAAAA.html")

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

    previous_blocked_threshold = settings.ingestion_alert_blocked_failure_threshold
    previous_blocked_cooldown_seconds = settings.ingestion_safety_cooldown_blocked_seconds
    object.__setattr__(settings, "ingestion_alert_blocked_failure_threshold", 1)
    object.__setattr__(settings, "ingestion_safety_cooldown_blocked_seconds", 600)

    try:
        client = TestClient(app)
        login_user(client, email="api-runs-safety@example.com", password="api-password")
        headers = _api_csrf_headers(client)

        first_run_response = client.post(
            "/api/v1/runs/manual",
            headers={**headers, "Idempotency-Key": "safety-cooldown-run-1"},
        )
        assert first_run_response.status_code == 200

        settings_response = client.get("/api/v1/settings")
        assert settings_response.status_code == 200
        safety_state = settings_response.json()["data"]["safety_state"]
        _assert_safety_state_contract(safety_state)
        assert safety_state["cooldown_active"] is True
        assert safety_state["cooldown_reason"] == "blocked_failure_threshold_exceeded"
        assert int(safety_state["cooldown_remaining_seconds"]) > 0
        assert int(safety_state["counters"]["cooldown_entry_count"]) >= 1
        assert int(safety_state["counters"]["last_blocked_failure_count"]) >= 1

        blocked_start_response = client.post(
            "/api/v1/runs/manual",
            headers={**headers, "Idempotency-Key": "safety-cooldown-run-2"},
        )
        assert blocked_start_response.status_code == 429
        blocked_payload = blocked_start_response.json()
        assert blocked_payload["error"]["code"] == "scrape_cooldown_active"
        blocked_state = blocked_payload["error"]["details"]["safety_state"]
        _assert_safety_state_contract(blocked_state)
        assert blocked_state["cooldown_active"] is True
        assert blocked_state["cooldown_reason"] == "blocked_failure_threshold_exceeded"
        assert int(blocked_state["counters"]["blocked_start_count"]) >= 1

        runs_response = client.get("/api/v1/runs")
        assert runs_response.status_code == 200
        _assert_safety_state_contract(runs_response.json()["data"]["safety_state"])
        assert runs_response.json()["data"]["safety_state"]["cooldown_active"] is True
    finally:
        object.__setattr__(settings, "ingestion_alert_blocked_failure_threshold", previous_blocked_threshold)
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
        client = TestClient(app)
        login_user(client, email="api-runs-safety-network@example.com", password="api-password")
        headers = _api_csrf_headers(client)

        first_run_response = client.post(
            "/api/v1/runs/manual",
            headers={**headers, "Idempotency-Key": "safety-network-cooldown-run-1"},
        )
        assert first_run_response.status_code == 200

        settings_response = client.get("/api/v1/settings")
        assert settings_response.status_code == 200
        safety_state = settings_response.json()["data"]["safety_state"]
        _assert_safety_state_contract(safety_state)
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
        _assert_safety_state_contract(blocked_state)
        assert blocked_state["cooldown_active"] is True
        assert blocked_state["cooldown_reason"] == "network_failure_threshold_exceeded"
        assert int(blocked_state["counters"]["blocked_start_count"]) >= 1
    finally:
        object.__setattr__(settings, "ingestion_alert_network_failure_threshold", previous_network_threshold)
        object.__setattr__(settings, "ingestion_safety_cooldown_network_seconds", previous_network_cooldown_seconds)
        object.__setattr__(settings, "ingestion_network_error_retries", previous_network_retries)
        object.__setattr__(settings, "ingestion_retry_backoff_seconds", previous_retry_backoff)
        app.dependency_overrides.pop(get_scholar_source, None)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_settings_clears_expired_scrape_safety_cooldown(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-settings-safety-expired@example.com",
        password="api-password",
    )
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=user_id,
    )
    user_settings.scrape_safety_state = {"blocked_start_count": 2}
    user_settings.scrape_cooldown_reason = "blocked_failure_threshold_exceeded"
    user_settings.scrape_cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=15)
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-settings-safety-expired@example.com", password="api-password")

    settings_response = client.get("/api/v1/settings")
    assert settings_response.status_code == 200
    settings_safety_state = settings_response.json()["data"]["safety_state"]
    _assert_safety_state_contract(settings_safety_state)
    assert settings_safety_state["cooldown_active"] is False
    assert settings_safety_state["cooldown_reason"] is None
    assert int(settings_safety_state["counters"]["blocked_start_count"]) == 2

    runs_response = client.get("/api/v1/runs")
    assert runs_response.status_code == 200
    runs_safety_state = runs_response.json()["data"]["safety_state"]
    _assert_safety_state_contract(runs_safety_state)
    assert runs_safety_state["cooldown_active"] is False
    assert runs_safety_state["cooldown_reason"] is None


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
            INSERT INTO publications (
                fingerprint_sha256,
                title_raw,
                title_normalized,
                citation_count,
                pdf_url
            )
            VALUES (:fingerprint, :title_raw, :title_normalized, 10, :pdf_url)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{user_id:064x}",
            "title_raw": "Paper A",
            "title_normalized": "paper a",
            "pdf_url": "https://example.org/paper-a.pdf",
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
    assert data["total_count"] == 2
    assert data["unread_count"] == 2
    assert data["latest_count"] == 0
    assert data["new_count"] == data["latest_count"]
    assert isinstance(data["publications"], list)
    assert len(data["publications"]) == 2
    pdf_urls = {item["title"]: item["pdf_url"] for item in data["publications"]}
    assert pdf_urls["Paper A"] == "https://example.org/paper-a.pdf"
    assert pdf_urls["Paper B"] is None

    latest_response = client.get("/api/v1/publications?mode=latest")
    assert latest_response.status_code == 200
    latest_data = latest_response.json()["data"]
    assert latest_data["mode"] == "latest"
    assert latest_data["latest_count"] == 0

    unread_response = client.get("/api/v1/publications?mode=unread")
    assert unread_response.status_code == 200
    unread_data = unread_response.json()["data"]
    assert unread_data["mode"] == "unread"
    assert unread_data["unread_count"] == 2

    alias_response = client.get("/api/v1/publications?mode=new")
    assert alias_response.status_code == 200
    alias_data = alias_response.json()["data"]
    assert alias_data["mode"] == "latest"
    assert alias_data["latest_count"] == latest_data["latest_count"]
    assert alias_data["publications"] == latest_data["publications"]

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


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_unread_and_latest_modes_can_diverge(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-mismatch@example.com",
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
            "scholar_id": "mismatchScholar01",
            "display_name": "Mismatch Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    older_run_result = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
            VALUES (:user_id, 'manual', 'success', 1, 1)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    older_run_id = int(older_run_result.scalar_one())

    latest_run_result = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
            VALUES (:user_id, 'scheduled', 'success', 1, 0)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    latest_run_id = int(latest_run_result.scalar_one())
    assert latest_run_id > older_run_id

    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 12)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 99):064x}",
            "title_raw": "Unread But Not Latest",
            "title_normalized": "unread but not latest",
        },
    )
    publication_id = int(publication_result.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (
                scholar_profile_id,
                publication_id,
                is_read,
                first_seen_run_id
            )
            VALUES (:scholar_profile_id, :publication_id, false, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_id": publication_id,
            "first_seen_run_id": older_run_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs-mismatch@example.com", password="api-password")

    unread_response = client.get("/api/v1/publications?mode=unread")
    assert unread_response.status_code == 200
    unread_data = unread_response.json()["data"]
    assert unread_data["mode"] == "unread"
    assert unread_data["unread_count"] == 1
    assert unread_data["latest_count"] == 0
    assert unread_data["new_count"] == 0
    assert len(unread_data["publications"]) == 1
    assert int(unread_data["publications"][0]["publication_id"]) == publication_id
    assert unread_data["publications"][0]["is_new_in_latest_run"] is False

    latest_response = client.get("/api/v1/publications?mode=latest")
    assert latest_response.status_code == 200
    latest_data = latest_response.json()["data"]
    assert latest_data["mode"] == "latest"
    assert latest_data["latest_count"] == 0
    assert len(latest_data["publications"]) == 0

    alias_response = client.get("/api/v1/publications?mode=new")
    assert alias_response.status_code == 200
    alias_data = alias_response.json()["data"]
    assert alias_data["mode"] == "latest"
    assert alias_data["latest_count"] == latest_data["latest_count"]
    assert alias_data["publications"] == latest_data["publications"]
