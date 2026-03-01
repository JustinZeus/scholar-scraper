from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.settings import settings
from tests.integration.helpers import (
    api_bootstrap_csrf_headers,
    api_csrf_headers,
    insert_user,
    login_user,
    seed_publication_link_for_user,
)


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
    headers = api_csrf_headers(client)

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

    target_headers = api_bootstrap_csrf_headers(client)
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
async def test_api_admin_scholar_http_settings_endpoints(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-admin-http@example.com",
        password="admin-password",
        is_admin=True,
    )
    await insert_user(
        db_session,
        email="api-member-http@example.com",
        password="member-password",
        is_admin=False,
    )
    previous_user_agent = settings.scholar_http_user_agent
    previous_rotate = settings.scholar_http_rotate_user_agent
    previous_accept_language = settings.scholar_http_accept_language
    previous_cookie = settings.scholar_http_cookie
    try:
        client = TestClient(app)
        login_user(client, email="api-admin-http@example.com", password="admin-password")
        headers = api_csrf_headers(client)

        read_response = client.get("/api/v1/admin/settings/scholar-http")
        assert read_response.status_code == 200

        update_response = client.put(
            "/api/v1/admin/settings/scholar-http",
            json={
                "user_agent": "Mozilla/5.0 Test Runner",
                "rotate_user_agent": False,
                "accept_language": "en-US,en;q=0.8",
                "cookie": "SID=test-cookie",
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        payload = update_response.json()["data"]
        assert payload["user_agent"] == "Mozilla/5.0 Test Runner"
        assert payload["cookie"] == "SID=test-cookie"
        assert settings.scholar_http_user_agent == "Mozilla/5.0 Test Runner"

        client.post("/api/v1/auth/logout", headers=headers)
        login_user(client, email="api-member-http@example.com", password="member-password")
        forbidden_response = client.get("/api/v1/admin/settings/scholar-http")
        assert forbidden_response.status_code == 403
    finally:
        object.__setattr__(settings, "scholar_http_user_agent", previous_user_agent)
        object.__setattr__(settings, "scholar_http_rotate_user_agent", previous_rotate)
        object.__setattr__(settings, "scholar_http_accept_language", previous_accept_language)
        object.__setattr__(settings, "scholar_http_cookie", previous_cookie)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_dbops_integrity_and_repair_flow(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="api-admin-dbops@example.com", password="admin-password", is_admin=True)
    target_user_id = await insert_user(db_session, email="api-dbops-target@example.com", password="target-password")
    _scholar_id, publication_id = await seed_publication_link_for_user(
        db_session,
        user_id=target_user_id,
        scholar_id="dbopsTarget01",
        title="DB Ops Target Paper",
        fingerprint=f"{(target_user_id + 31):064x}",
    )
    client = TestClient(app)
    login_user(client, email="api-admin-dbops@example.com", password="admin-password")
    headers = api_csrf_headers(client)

    integrity_response = client.get("/api/v1/admin/db/integrity")
    assert integrity_response.status_code == 200
    integrity_payload = integrity_response.json()["data"]
    assert integrity_payload["status"] in {"ok", "warning", "failed"}
    assert any(check["name"] == "missing_pdf_url" for check in integrity_payload["checks"])

    repair_response = client.post(
        "/api/v1/admin/db/repairs/publication-links",
        json={"user_id": target_user_id, "dry_run": True},
        headers=headers,
    )
    assert repair_response.status_code == 200
    repair_data = repair_response.json()["data"]
    assert repair_data["status"] == "completed"
    assert bool(repair_data["summary"]["dry_run"]) is True
    job_id = int(repair_data["job_id"])

    jobs_response = client.get("/api/v1/admin/db/repair-jobs?limit=10")
    assert jobs_response.status_code == 200
    jobs = jobs_response.json()["data"]["jobs"]
    assert any(int(job["id"]) == job_id for job in jobs)

    pdf_queue_response = client.get("/api/v1/admin/db/pdf-queue?limit=20")
    assert pdf_queue_response.status_code == 200
    pdf_queue_payload = pdf_queue_response.json()["data"]
    assert isinstance(pdf_queue_payload["items"], list)
    assert int(pdf_queue_payload["page"]) == 1
    assert int(pdf_queue_payload["page_size"]) == 20
    assert int(pdf_queue_payload["total_count"]) >= 0
    assert isinstance(pdf_queue_payload["has_next"], bool)
    assert isinstance(pdf_queue_payload["has_prev"], bool)
    page_two_response = client.get("/api/v1/admin/db/pdf-queue?page=2&page_size=1")
    assert page_two_response.status_code == 200
    page_two_payload = page_two_response.json()["data"]
    assert int(page_two_payload["page"]) == 2
    assert int(page_two_payload["page_size"]) == 1
    assert page_two_payload["has_prev"] is True
    untracked_response = client.get("/api/v1/admin/db/pdf-queue?limit=20&status=untracked")
    assert untracked_response.status_code == 200
    assert any(item["status"] == "untracked" for item in untracked_response.json()["data"]["items"])

    link_count_result = await db_session.execute(
        text("SELECT count(*) FROM scholar_publications WHERE publication_id = :publication_id"),
        {"publication_id": publication_id},
    )
    assert int(link_count_result.scalar_one()) == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_dbops_pdf_queue_requeue_endpoint(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await insert_user(db_session, email="api-admin-pdf@example.com", password="admin-password", is_admin=True)
    target_user_id = await insert_user(db_session, email="api-pdf-target@example.com", password="target-password")
    _scholar_id, publication_id = await seed_publication_link_for_user(
        db_session,
        user_id=target_user_id,
        scholar_id="dbopsPdf01",
        title="PDF Queue Target",
        fingerprint=f"{(target_user_id + 73):064x}",
    )
    monkeypatch.setattr(
        "app.services.publications.pdf_queue.schedule_rows",
        lambda **_kwargs: None,
    )
    client = TestClient(app)
    login_user(client, email="api-admin-pdf@example.com", password="admin-password")
    headers = api_csrf_headers(client)

    first_response = client.post(
        f"/api/v1/admin/db/pdf-queue/{publication_id}/requeue",
        headers=headers,
    )
    assert first_response.status_code == 200
    first_data = first_response.json()["data"]
    assert first_data["publication_id"] == publication_id
    assert first_data["queued"] is True
    assert first_data["status"] == "queued"

    second_response = client.post(
        f"/api/v1/admin/db/pdf-queue/{publication_id}/requeue",
        headers=headers,
    )
    assert second_response.status_code == 200
    second_data = second_response.json()["data"]
    assert second_data["queued"] is False
    assert second_data["status"] == "blocked"


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_dbops_pdf_queue_requeue_all_endpoint(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await insert_user(db_session, email="api-admin-pdf-all@example.com", password="admin-password", is_admin=True)
    target_user_id = await insert_user(db_session, email="api-pdf-all-target@example.com", password="target-password")
    _scholar_id, _publication_id = await seed_publication_link_for_user(
        db_session,
        user_id=target_user_id,
        scholar_id="dbopsPdfAll01",
        title="PDF Queue All Target",
        fingerprint=f"{(target_user_id + 83):064x}",
    )
    monkeypatch.setattr(
        "app.services.publications.pdf_queue.schedule_rows",
        lambda **_kwargs: None,
    )
    client = TestClient(app)
    login_user(client, email="api-admin-pdf-all@example.com", password="admin-password")
    headers = api_csrf_headers(client)

    response = client.post(
        "/api/v1/admin/db/pdf-queue/requeue-all?limit=500",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert int(payload["requested_count"]) >= 1
    assert int(payload["queued_count"]) >= 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_dbops_forbidden_for_non_admin_and_validates_scope(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="api-admin-dbops2@example.com", password="admin-password", is_admin=True)
    member_user_id = await insert_user(db_session, email="api-dbops-member@example.com", password="member-password")
    client = TestClient(app)
    login_user(client, email="api-dbops-member@example.com", password="member-password")
    headers = api_csrf_headers(client)

    forbidden_integrity = client.get("/api/v1/admin/db/integrity")
    assert forbidden_integrity.status_code == 403
    assert forbidden_integrity.json()["error"]["code"] == "forbidden"

    forbidden_pdf_queue = client.get("/api/v1/admin/db/pdf-queue")
    assert forbidden_pdf_queue.status_code == 403
    assert forbidden_pdf_queue.json()["error"]["code"] == "forbidden"

    forbidden_requeue = client.post(
        "/api/v1/admin/db/pdf-queue/1/requeue",
        headers=headers,
    )
    assert forbidden_requeue.status_code == 403
    assert forbidden_requeue.json()["error"]["code"] == "forbidden"

    forbidden_requeue_all = client.post(
        "/api/v1/admin/db/pdf-queue/requeue-all?limit=100",
        headers=headers,
    )
    assert forbidden_requeue_all.status_code == 403
    assert forbidden_requeue_all.json()["error"]["code"] == "forbidden"

    forbidden_repair = client.post(
        "/api/v1/admin/db/repairs/publication-links",
        json={"user_id": member_user_id, "dry_run": True},
        headers=headers,
    )
    assert forbidden_repair.status_code == 403
    assert forbidden_repair.json()["error"]["code"] == "forbidden"

    forbidden_near_duplicate = client.post(
        "/api/v1/admin/db/repairs/publication-near-duplicates",
        json={"dry_run": True},
        headers=headers,
    )
    assert forbidden_near_duplicate.status_code == 403
    assert forbidden_near_duplicate.json()["error"]["code"] == "forbidden"

    admin_headers = api_bootstrap_csrf_headers(client)
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "api-admin-dbops2@example.com", "password": "admin-password"},
        headers=admin_headers,
    )
    assert admin_login.status_code == 200
    post_login_headers = {"X-CSRF-Token": admin_login.json()["data"]["csrf_token"]}
    invalid_scope = client.post(
        "/api/v1/admin/db/repairs/publication-links",
        json={"user_id": member_user_id, "dry_run": True},
        headers=post_login_headers,
    )
    assert invalid_scope.status_code == 400
    assert invalid_scope.json()["error"]["code"] == "invalid_repair_scope"


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_dbops_all_users_apply_requires_confirmation(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="api-admin-dbops3@example.com", password="admin-password", is_admin=True)
    first_user_id = await insert_user(db_session, email="api-dbops-a@example.com", password="user-password")
    second_user_id = await insert_user(db_session, email="api-dbops-b@example.com", password="user-password")
    await seed_publication_link_for_user(
        db_session,
        user_id=first_user_id,
        scholar_id="dbopsAll01",
        title="DB Ops All User Paper One",
        fingerprint=f"{(first_user_id + 61):064x}",
    )
    await seed_publication_link_for_user(
        db_session,
        user_id=second_user_id,
        scholar_id="dbopsAll02",
        title="DB Ops All User Paper Two",
        fingerprint=f"{(second_user_id + 71):064x}",
    )

    client = TestClient(app)
    login_user(client, email="api-admin-dbops3@example.com", password="admin-password")
    headers = api_csrf_headers(client)

    missing_confirmation = client.post(
        "/api/v1/admin/db/repairs/publication-links",
        json={"scope_mode": "all_users", "dry_run": False},
        headers=headers,
    )
    assert missing_confirmation.status_code == 422
    assert "confirmation_text" in str(missing_confirmation.json())

    apply_response = client.post(
        "/api/v1/admin/db/repairs/publication-links",
        json={
            "scope_mode": "all_users",
            "dry_run": False,
            "confirmation_text": "REPAIR ALL USERS",
        },
        headers=headers,
    )
    assert apply_response.status_code == 200
    apply_data = apply_response.json()["data"]
    assert apply_data["status"] == "completed"
    assert apply_data["scope"]["scope_mode"] == "all_users"
    assert int(apply_data["summary"]["links_deleted"]) >= 2

    remaining_links = await db_session.execute(text("SELECT count(*) FROM scholar_publications"))
    assert int(remaining_links.scalar_one()) == 0


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_admin_dbops_near_duplicate_repair_scan_and_apply(
    db_session: AsyncSession,
) -> None:
    await insert_user(
        db_session,
        email="api-admin-near-dup@example.com",
        password="admin-password",
        is_admin=True,
    )
    user_id = await insert_user(
        db_session,
        email="api-near-dup-target@example.com",
        password="user-password",
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
            "scholar_id": "nearDupScholar01",
            "display_name": "Near Dup Target",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    first_pub = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, year, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 2014, 100)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1201):064x}",
            "title_raw": "Adam: A method for stochastic optimization",
            "title_normalized": "adam a method for stochastic optimization",
        },
    )
    first_publication_id = int(first_pub.scalar_one())
    second_pub = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, year, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 2015, 10)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1202):064x}",
            "title_raw": "â€ œAdam: A method for stochastic optimization, â€ 3rd Int. Conf. Learn. Represent.",
            "title_normalized": "adam method for stochastic optimization",
        },
    )
    second_publication_id = int(second_pub.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read)
            VALUES (:scholar_profile_id, :first_publication_id, false),
                   (:scholar_profile_id, :second_publication_id, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "first_publication_id": first_publication_id,
            "second_publication_id": second_publication_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-admin-near-dup@example.com", password="admin-password")
    headers = api_csrf_headers(client)

    scan_response = client.post(
        "/api/v1/admin/db/repairs/publication-near-duplicates",
        json={"dry_run": True, "max_clusters": 20},
        headers=headers,
    )
    assert scan_response.status_code == 200
    scan_data = scan_response.json()["data"]
    assert scan_data["status"] == "completed"
    assert int(scan_data["summary"]["candidate_cluster_count"]) >= 1
    assert len(scan_data["clusters"]) >= 1
    selected_key = str(scan_data["clusters"][0]["cluster_key"])

    missing_confirmation = client.post(
        "/api/v1/admin/db/repairs/publication-near-duplicates",
        json={"dry_run": False, "selected_cluster_keys": [selected_key]},
        headers=headers,
    )
    assert missing_confirmation.status_code == 422
    assert "confirmation_text" in str(missing_confirmation.json())

    apply_response = client.post(
        "/api/v1/admin/db/repairs/publication-near-duplicates",
        json={
            "dry_run": False,
            "selected_cluster_keys": [selected_key],
            "confirmation_text": "MERGE SELECTED DUPLICATES",
        },
        headers=headers,
    )
    assert apply_response.status_code == 200
    apply_data = apply_response.json()["data"]
    assert apply_data["status"] == "completed"
    assert int(apply_data["summary"]["merged_publications"]) >= 1

    remaining = await db_session.execute(
        text(
            """
            SELECT count(*)
            FROM publications
            WHERE id IN (:first_publication_id, :second_publication_id)
            """
        ),
        {
            "first_publication_id": first_publication_id,
            "second_publication_id": second_publication_id,
        },
    )
    assert int(remaining.scalar_one()) == 1
