import re
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.auth.deps import get_auth_service, get_login_rate_limiter
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.db.session import get_db_session
from app.main import app

CSRF_TOKEN_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


class StubAuthService:
    def __init__(self, *, user: object | None) -> None:
        self._user = user

    async def authenticate_user(self, _db_session, *, email: str, password: str):
        if self._user is None:
            return None
        if email.strip().lower() != str(self._user.email):
            return None
        if password != "correct-password":
            return None
        return self._user


def _extract_csrf_token(html: str) -> str:
    match = CSRF_TOKEN_PATTERN.search(html)
    assert match is not None
    return match.group(1)


async def _override_db_session() -> AsyncIterator[object]:
    yield object()


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> AsyncIterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_login_requires_csrf_token() -> None:
    client = TestClient(app)

    response = client.post(
        "/login",
        data={"email": "user@example.com", "password": "correct-password"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.text == "CSRF token missing."


def test_successful_login_creates_session_and_allows_dashboard(monkeypatch) -> None:
    limiter = SlidingWindowRateLimiter(max_attempts=5, window_seconds=60)
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_auth_service] = lambda: StubAuthService(
        user=SimpleNamespace(id=1, email="user@example.com", is_admin=False)
    )
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    client = TestClient(app)
    monkeypatch.setattr(
        "app.web.common.get_authenticated_user",
        AsyncMock(
            return_value=SimpleNamespace(
                id=1,
                email="user@example.com",
                is_admin=False,
            )
        ),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.publication_service.list_new_for_latest_run_for_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.run_service.list_recent_runs_for_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.run_service.queue_status_counts_for_user",
        AsyncMock(return_value={"queued": 0, "retrying": 0, "dropped": 0}),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.user_settings_service.get_or_create_settings",
        AsyncMock(return_value=SimpleNamespace(request_delay_seconds=0)),
    )

    login_page = client.get("/login")
    csrf_token = _extract_csrf_token(login_page.text)

    login_response = client.post(
        "/login",
        data={
            "email": "user@example.com",
            "password": "correct-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"

    dashboard_response = client.get("/")
    assert dashboard_response.status_code == 200
    assert 'data-test="home-hero"' in dashboard_response.text
    assert 'data-test="session-user"' in dashboard_response.text
    assert "user@example.com" in dashboard_response.text


def test_login_rate_limiting_returns_429_after_threshold() -> None:
    limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60)
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_auth_service] = lambda: StubAuthService(user=None)
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    client = TestClient(app)

    login_page = client.get("/login")
    csrf_token = _extract_csrf_token(login_page.text)
    payload = {
        "email": "user@example.com",
        "password": "wrong-password",
        "csrf_token": csrf_token,
    }

    first = client.post("/login", data=payload, follow_redirects=False)
    second = client.post("/login", data=payload, follow_redirects=False)
    third = client.post("/login", data=payload, follow_redirects=False)

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"


def test_logout_requires_csrf_token_and_clears_session(monkeypatch) -> None:
    limiter = SlidingWindowRateLimiter(max_attempts=5, window_seconds=60)
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_auth_service] = lambda: StubAuthService(
        user=SimpleNamespace(id=1, email="user@example.com", is_admin=False)
    )
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    client = TestClient(app)
    monkeypatch.setattr(
        "app.web.common.get_authenticated_user",
        AsyncMock(
            side_effect=[
                SimpleNamespace(id=1, email="user@example.com", is_admin=False),
                None,
            ]
        ),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.publication_service.list_new_for_latest_run_for_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.run_service.list_recent_runs_for_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.run_service.queue_status_counts_for_user",
        AsyncMock(return_value={"queued": 0, "retrying": 0, "dropped": 0}),
    )
    monkeypatch.setattr(
        "app.web.routers.dashboard.user_settings_service.get_or_create_settings",
        AsyncMock(return_value=SimpleNamespace(request_delay_seconds=0)),
    )

    login_page = client.get("/login")
    csrf_token = _extract_csrf_token(login_page.text)
    client.post(
        "/login",
        data={
            "email": "user@example.com",
            "password": "correct-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    failed_logout = client.post("/logout", data={}, follow_redirects=False)
    assert failed_logout.status_code == 403
    assert failed_logout.text == "CSRF token invalid."

    dashboard_page = client.get("/")
    logout_token = _extract_csrf_token(dashboard_page.text)
    successful_logout = client.post(
        "/logout",
        data={"csrf_token": logout_token},
        follow_redirects=False,
    )

    assert successful_logout.status_code == 303
    assert successful_logout.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
