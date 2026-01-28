import pytest
import os
import shutil
from pathlib import Path

@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    """Sets up a mock environment for testing."""
    # Set up temporary directories for secrets
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    
    # Clean up interfering env vars that might be set in the user's session
    vars_to_clear = [
        "ADMIN_USERNAME", "ADMIN_SECRET", "ADMIN_PASSWORD_HASH", "ALLOWED_CLIENT_IPS",
        "LOG_LEVEL", "SERVICES__MAX_RETRIES", 
        "SECURITY__ADMIN_USERNAME", "SECURITY__ADMIN_SECRET"
    ]
    for var in vars_to_clear:
        monkeypatch.delenv(var, raising=False)
        
    # Hide .env file if it exists to ensure tests are isolated
    env_file = Path(".env")
    renamed_env = False
    if env_file.exists():
        env_file.rename(".env.test_backup")
        renamed_env = True
        
    # Mock environment variables
    # Note: SecuritySettings is a BaseSettings, so it reads ADMIN_SECRET directly too if not namespaced properly in app.
    # But we want to test via the main Settings object which nests it.
    # To be safe and consistent with app logic (which likely relies on nested behavior),
    # we set vars that match what the app likely expects or what pydantic-settings maps.
    
    monkeypatch.setenv("ENCRYPTION_KEY_FILE", str(secrets_dir / "master.key"))
    monkeypatch.setenv("SECURITY__ADMIN_SECRET", "test-secret-key-123456")
    monkeypatch.setenv("PATHS__CREDS_ROOT", str(tmp_path / "credentials"))
    monkeypatch.setenv("SECURITY__ALLOWED_CLIENT_IPS", '["127.0.0.1", "test-ip"]')
    
    yield tmp_path
    
    # Restore .env file
    if renamed_env:
        Path(".env.test_backup").rename(".env")