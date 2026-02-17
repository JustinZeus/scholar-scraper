from fastapi.testclient import TestClient

from app.main import app


def test_home_page_redirects_to_login_when_unauthenticated() -> None:
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dev_ui_page_is_removed() -> None:
    client = TestClient(app)

    response = client.get("/dev/ui", follow_redirects=False)

    assert response.status_code == 404


def test_login_page_renders_html() -> None:
    client = TestClient(app)

    response = client.get("/login")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "scholarr" in response.text
    assert 'data-test="login-form"' in response.text
    assert 'name="csrf_token"' in response.text
    assert 'data-theme-control' in response.text
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_theme_query_parameter_accepts_supported_theme() -> None:
    client = TestClient(app)

    response = client.get("/login?theme=spruce")

    assert response.status_code == 200
    assert 'data-theme="spruce"' in response.text


def test_theme_query_parameter_falls_back_for_unknown_theme() -> None:
    client = TestClient(app)

    response = client.get("/login?theme=not-a-theme")

    assert response.status_code == 200
    assert 'data-theme="terracotta"' in response.text
