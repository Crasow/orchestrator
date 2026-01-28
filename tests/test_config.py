import os
import pytest
from app.config import Settings, get_settings, ensure_directories


def test_settings_load_defaults(mock_env):
    """Test that settings load with default values when env vars are not set (except required ones)."""
    # Force reload of settings to pick up mocked env
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.log_level == "INFO"
    assert settings.services.max_retries == 5
    assert settings.security.admin_username == "admin"


def test_settings_override_from_env(monkeypatch, mock_env):
    """Test that environment variables override defaults."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SERVICES__MAX_RETRIES", "10")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.log_level == "DEBUG"
    assert settings.services.max_retries == 10


def test_paths_configuration(mock_env):
    """Test that path configuration is correct."""
    get_settings.cache_clear()
    settings = get_settings()

    creds_root = settings.paths.creds_root
    assert str(creds_root) == os.environ["PATHS__CREDS_ROOT"]
    assert settings.paths.vertex_creds_dir == creds_root / "vertex"
    assert settings.paths.gemini_creds_dir == creds_root / "gemini"
    assert settings.paths.gemini_keys_file == creds_root / "gemini" / "api_keys.json"


def test_ensure_directories(mock_env):
    """Test that ensure_directories creates the required structure."""
    get_settings.cache_clear()
    settings = get_settings()

    # Ensure dirs don't exist yet (in our temp path)
    assert not settings.paths.vertex_creds_dir.exists()
    assert not settings.paths.gemini_creds_dir.exists()

    ensure_directories()

    assert settings.paths.vertex_creds_dir.exists()
    assert settings.paths.gemini_creds_dir.exists()
    assert settings.paths.gemini_keys_file.exists()

    # Check content of gemini keys file
    with open(settings.paths.gemini_keys_file, "r") as f:
        assert f.read() == "[]"
