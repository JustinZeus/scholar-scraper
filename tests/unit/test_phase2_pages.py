from fastapi.testclient import TestClient

from app.main import app


def test_phase2_pages_redirect_to_login_when_unauthenticated() -> None:
    client = TestClient(app)

    for path in (
        "/users",
        "/runs",
        "/runs/1",
        "/publications",
        "/scholars",
        "/settings",
        "/account/password",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
