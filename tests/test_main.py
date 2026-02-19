import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock

from app.config import get_settings


@pytest.fixture
def client(mock_env):
    """Test client fixture."""
    get_settings.cache_clear()

    # Mock DB engine and session to avoid real DB connection during tests
    with patch("app.db.engine.create_async_engine") as mock_engine, \
         patch("app.main.async_engine") as mock_main_engine, \
         patch("app.main.async_session_factory"), \
         patch("app.main.Base"):
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_main_engine.begin.return_value = mock_ctx
        mock_main_engine.dispose = AsyncMock()

        # Mock async_engine.connect() for health check
        mock_connect_ctx = AsyncMock()
        mock_connect_conn = AsyncMock()
        mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_connect_conn)
        mock_connect_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_main_engine.connect.return_value = mock_connect_ctx

        from app.main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def admin_auth(monkeypatch):
    """Sets up admin credentials in env vars and returns valid headers."""
    from app.security.auth import auth_manager
    password = "secret-password"
    pw_hash = auth_manager.hash_password(password)

    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", pw_hash)

    return {"username": "admin", "password": password}


def _login(client, admin_auth) -> TestClient:
    """Login and return client with cookie set."""
    response = client.post("/admin/login", json=admin_auth)
    assert response.status_code == 200
    assert "access_token" in response.cookies
    return client


def test_health_check(client):
    """Test health check endpoint returns status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "gemini_keys" in data
    assert "vertex_credentials" in data


def test_admin_login_success(client, admin_auth):
    """Test successful admin login sets cookie."""
    response = client.post("/admin/login", json=admin_auth)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["username"] == "admin"
    # Cookie should be set
    assert "access_token" in response.cookies


def test_admin_login_fail(client, admin_auth):
    """Test failed admin login."""
    response = client.post("/admin/login", json={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 401

    response = client.post("/admin/login", json={"username": "wrong", "password": "secret-password"})
    assert response.status_code == 401


def test_admin_logout(client, admin_auth):
    """Test logout clears cookie."""
    _login(client, admin_auth)
    response = client.post("/admin/logout")
    assert response.status_code == 200
    # Set-Cookie header should delete the cookie (max-age=0 or expires in the past)
    set_cookie = response.headers.get("set-cookie", "")
    assert "access_token" in set_cookie
    assert 'max-age=0' in set_cookie.lower() or "expires" in set_cookie.lower()


def test_admin_status_protected(client):
    """Test that /admin/status requires authentication."""
    response = client.get("/admin/status")
    assert response.status_code == 401


def test_admin_status_success(client, admin_auth):
    """Test /admin/status with cookie auth."""
    _login(client, admin_auth)

    with patch("app.api.admin.state") as mock_state:
        mock_state.vertex_rotator.credential_count = 0
        mock_state.gemini_rotator.key_count = 0

        response = client.get("/admin/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
        assert data["admin_user"] == "admin"


def test_admin_reload(client, admin_auth):
    """Test /admin/reload endpoint with cookie auth."""
    _login(client, admin_auth)

    with patch("app.api.admin.state") as mock_state:
        mock_state.vertex_rotator.credential_count = 0
        mock_state.gemini_rotator.key_count = 0

        response = client.post("/admin/reload")

        assert response.status_code == 200
        assert mock_state.vertex_rotator.reload.called
        assert mock_state.gemini_rotator.reload.called


def test_bearer_header_still_works(client, admin_auth):
    """Test backward compatibility: Authorization header still works."""
    from app.security.auth import auth_manager
    # Create token with testclient IP (that's what TestClient reports)
    token = auth_manager.authenticate_admin(
        admin_auth["username"], admin_auth["password"], "testclient"
    )

    with patch("app.api.admin.state") as mock_state:
        mock_state.vertex_rotator.credential_count = 0
        mock_state.gemini_rotator.key_count = 0

        response = client.get(
            "/admin/status",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
