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
        # Mock the engine.begin() async context manager for create_all
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_main_engine.begin.return_value = mock_ctx
        mock_main_engine.dispose = AsyncMock()

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


def test_health_check_via_proxy(client):
    pass


def test_admin_login_success(client, admin_auth):
    """Test successful admin login."""
    response = client.post("/admin/login", json=admin_auth)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_admin_login_fail(client, admin_auth):
    """Test failed admin login."""
    response = client.post("/admin/login", json={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 401

    response = client.post("/admin/login", json={"username": "wrong", "password": "secret-password"})
    assert response.status_code == 401


def test_admin_status_protected(client):
    """Test that /admin/status requires authentication."""
    response = client.get("/admin/status")
    assert response.status_code == 401


def test_admin_status_success(client, admin_auth):
    """Test /admin/status with valid token."""
    login_res = client.post("/admin/login", json=admin_auth)
    token = login_res.json()["access_token"]

    with patch("app.api.admin.vertex_rotator") as mock_vertex, \
         patch("app.api.admin.gemini_rotator") as mock_gemini, \
         patch("app.security.audit.security_auditor") as mock_auditor:

        mock_vertex._pool = []
        mock_gemini._keys = []
        mock_auditor.get_suspicious_activity.return_value = []

        response = client.get(
            "/admin/status",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
        assert data["admin_user"] == "admin"


def test_admin_reload(client, admin_auth):
    """Test /admin/reload endpoint."""
    login_res = client.post("/admin/login", json=admin_auth)
    token = login_res.json()["access_token"]

    with patch("app.api.admin.vertex_rotator") as mock_vertex, \
         patch("app.api.admin.gemini_rotator") as mock_gemini:

        mock_vertex._pool = []
        mock_gemini._keys = []

        response = client.post(
            "/admin/reload",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert mock_vertex.reload.called
        assert mock_gemini.reload.called
