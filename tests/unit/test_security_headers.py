from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app


def test_security_headers_are_set_for_api_responses(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database", AsyncMock(return_value=True))
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "permissions-policy" in response.headers
    assert "content-security-policy" in response.headers
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_docs_route_uses_docs_csp_policy(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database", AsyncMock(return_value=True))
    client = TestClient(app)

    response = client.get("/docs")

    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
