from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_200_when_database_is_available(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database", AsyncMock(return_value=True))
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_returns_500_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database", AsyncMock(return_value=False))
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 500
    assert response.json()["detail"] == "database unavailable"
