from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from tests.integration.helpers import (
    api_csrf_headers,
    insert_user,
    login_user,
)


def _create_scholar(client: TestClient, headers: dict, scholar_id: str) -> int:
    resp = client.post("/api/v1/scholars", json={"scholar_id": scholar_id}, headers=headers)
    assert resp.status_code == 201
    return int(resp.json()["data"]["id"])


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_bulk_delete_with_valid_ids(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="bulk@example.com", password="pw123456")
    client = TestClient(app)
    login_user(client, email="bulk@example.com", password="pw123456")
    headers = api_csrf_headers(client)

    id1 = _create_scholar(client, headers, "aaaBBB111222")
    id2 = _create_scholar(client, headers, "cccDDD333444")

    resp = client.post(
        "/api/v1/scholars/bulk-delete",
        json={"scholar_profile_ids": [id1, id2]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted_count"] == 2

    list_resp = client.get("/api/v1/scholars")
    assert len(list_resp.json()["data"]["scholars"]) == 0


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_bulk_delete_only_deletes_own_scholars(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="user1@example.com", password="pw123456")
    await insert_user(db_session, email="user2@example.com", password="pw123456")

    client1 = TestClient(app)
    login_user(client1, email="user1@example.com", password="pw123456")
    headers1 = api_csrf_headers(client1)

    client2 = TestClient(app)
    login_user(client2, email="user2@example.com", password="pw123456")
    headers2 = api_csrf_headers(client2)

    id_user1 = _create_scholar(client1, headers1, "aaaBBB111222")
    id_user2 = _create_scholar(client2, headers2, "cccDDD333444")

    # User1 tries to delete both — should only delete own
    resp = client1.post(
        "/api/v1/scholars/bulk-delete",
        json={"scholar_profile_ids": [id_user1, id_user2]},
        headers=headers1,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted_count"] == 1

    # User2's scholar still exists
    list_resp = client2.get("/api/v1/scholars")
    scholars = list_resp.json()["data"]["scholars"]
    assert len(scholars) == 1
    assert int(scholars[0]["id"]) == id_user2


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_bulk_toggle_enables_and_disables(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="toggle@example.com", password="pw123456")
    client = TestClient(app)
    login_user(client, email="toggle@example.com", password="pw123456")
    headers = api_csrf_headers(client)

    id1 = _create_scholar(client, headers, "aaaBBB111222")
    id2 = _create_scholar(client, headers, "cccDDD333444")

    # Disable both
    resp = client.post(
        "/api/v1/scholars/bulk-toggle",
        json={"scholar_profile_ids": [id1, id2], "is_enabled": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated_count"] == 2

    scholars = client.get("/api/v1/scholars").json()["data"]["scholars"]
    for s in scholars:
        assert s["is_enabled"] is False

    # Re-enable both
    resp = client.post(
        "/api/v1/scholars/bulk-toggle",
        json={"scholar_profile_ids": [id1, id2], "is_enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated_count"] == 2

    scholars = client.get("/api/v1/scholars").json()["data"]["scholars"]
    for s in scholars:
        assert s["is_enabled"] is True


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_export_with_ids_filter(db_session: AsyncSession) -> None:
    await insert_user(db_session, email="export@example.com", password="pw123456")
    client = TestClient(app)
    login_user(client, email="export@example.com", password="pw123456")
    headers = api_csrf_headers(client)

    id1 = _create_scholar(client, headers, "aaaBBB111222")
    _create_scholar(client, headers, "cccDDD333444")

    # Export only id1
    resp = client.get(f"/api/v1/scholars/export?ids={id1}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["scholars"]) == 1
    assert data["scholars"][0]["scholar_id"] == "aaaBBB111222"

    # Export all (no filter)
    resp_all = client.get("/api/v1/scholars/export")
    assert resp_all.status_code == 200
    assert len(resp_all.json()["data"]["scholars"]) == 2
