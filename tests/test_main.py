import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.security.auth import auth_manager

from app.config import get_settings

@pytest.fixture
def client(mock_env):
    """Test client fixture."""
    # Ensure settings are reloaded with mock_env
    get_settings.cache_clear()
    
    # Mock Redis to avoid connection errors during app initialization
    with patch("app.services.statistics.redis.from_url"):
        with TestClient(app) as c:
            yield c

@pytest.fixture
def admin_auth(monkeypatch):
    """Sets up admin credentials in env vars and returns valid headers."""
    password = "secret-password"
    # We use the auth_manager from the app to generate a consistent hash
    pw_hash = auth_manager.hash_password(password)
    
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", pw_hash)
    
    return {"username": "admin", "password": password}

def test_health_check_via_proxy(client):
    """
    Since there is no explicit health check endpoint, we can't test it directly 
    without mocking a provider.
    The /admin/status endpoint is the closest thing to a health check.
    """
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
    assert response.status_code == 401 # HTTPBearer/AuthManager returns 401

def test_admin_status_success(client, admin_auth):
    """Test /admin/status with valid token."""
    # Login first
    login_res = client.post("/admin/login", json=admin_auth)
    token = login_res.json()["access_token"]
    
    # Mock rotators to avoid actual logic errors
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
