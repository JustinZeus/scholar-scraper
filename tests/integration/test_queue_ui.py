from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from tests.integration.helpers import extract_csrf_token, insert_user, login_user


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_runs_page_queue_actions_lifecycle(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="queue-ui@example.com",
        password="queue-ui-password",
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
            "display_name": "Queue UI Scholar",
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
                last_error,
                dropped_reason,
                dropped_at
            )
            VALUES (
                :user_id,
                :scholar_profile_id,
                200,
                'dropped',
                'dropped',
                3,
                NOW() + INTERVAL '30 minutes',
                'captcha challenge',
                'max_attempts_after_run',
                NOW() - INTERVAL '1 minute'
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_profile_id": scholar_profile_id,
        },
    )
    queue_item_id = int(queue_result.scalar_one())
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="queue-ui@example.com", password="queue-ui-password")

    runs_page = client.get("/runs")
    assert runs_page.status_code == 200
    assert "Continuation Queue" in runs_page.text
    assert "Queue UI Scholar" in runs_page.text
    assert "dropped" in runs_page.text
    assert "max_attempts_after_run" in runs_page.text

    csrf_retry = extract_csrf_token(runs_page.text)
    retry_response = client.post(
        f"/runs/queue/{queue_item_id}/retry",
        data={"csrf_token": csrf_retry},
        follow_redirects=False,
    )
    assert retry_response.status_code == 303

    queue_after_retry = await db_session.execute(
        text(
            """
            SELECT status, reason, attempt_count
            FROM ingestion_queue_items
            WHERE id = :queue_item_id
            """
        ),
        {"queue_item_id": queue_item_id},
    )
    assert queue_after_retry.one() == ("queued", "manual_retry", 0)

    runs_page_after_retry = client.get("/runs")
    csrf_drop = extract_csrf_token(runs_page_after_retry.text)
    drop_response = client.post(
        f"/runs/queue/{queue_item_id}/drop",
        data={"csrf_token": csrf_drop},
        follow_redirects=False,
    )
    assert drop_response.status_code == 303

    queue_after_drop = await db_session.execute(
        text(
            """
            SELECT status, reason, dropped_reason
            FROM ingestion_queue_items
            WHERE id = :queue_item_id
            """
        ),
        {"queue_item_id": queue_item_id},
    )
    assert queue_after_drop.one() == ("dropped", "dropped", "manual_drop")

    runs_page_after_drop = client.get("/runs")
    csrf_clear = extract_csrf_token(runs_page_after_drop.text)
    clear_response = client.post(
        f"/runs/queue/{queue_item_id}/clear",
        data={"csrf_token": csrf_clear},
        follow_redirects=False,
    )
    assert clear_response.status_code == 303

    queue_after_clear = await db_session.execute(
        text("SELECT COUNT(*) FROM ingestion_queue_items WHERE id = :queue_item_id"),
        {"queue_item_id": queue_item_id},
    )
    assert queue_after_clear.scalar_one() == 0


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_runs_queue_actions_are_tenant_scoped(db_session: AsyncSession) -> None:
    user_a_id = await insert_user(
        db_session,
        email="queue-owner-a@example.com",
        password="queue-owner-a-password",
    )
    user_b_id = await insert_user(
        db_session,
        email="queue-owner-b@example.com",
        password="queue-owner-b-password",
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
            "user_id": user_b_id,
            "scholar_id": "zxyWVU654321",
            "display_name": "Owner B Queue Scholar",
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
                next_attempt_dt
            )
            VALUES (
                :user_id,
                :scholar_profile_id,
                0,
                'max_pages_reached',
                'queued',
                0,
                NOW()
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_b_id,
            "scholar_profile_id": scholar_profile_id,
        },
    )
    queue_item_id = int(queue_result.scalar_one())
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="queue-owner-a@example.com", password="queue-owner-a-password")

    runs_page = client.get("/runs")
    csrf_token = extract_csrf_token(runs_page.text)
    forbidden_retry = client.post(
        f"/runs/queue/{queue_item_id}/retry",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert forbidden_retry.status_code == 404

    unchanged = await db_session.execute(
        text(
            """
            SELECT status, reason, user_id
            FROM ingestion_queue_items
            WHERE id = :queue_item_id
            """
        ),
        {"queue_item_id": queue_item_id},
    )
    assert unchanged.one() == ("queued", "max_pages_reached", user_b_id)
    assert user_a_id != user_b_id
