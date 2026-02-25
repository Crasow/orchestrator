import pytest
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    """Sets up a mock environment for testing."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    vars_to_clear = [
        "ADMIN_USERNAME", "ADMIN_SECRET", "ADMIN_PASSWORD_HASH", "ALLOWED_CLIENT_IPS",
        "LOG_LEVEL", "SERVICES__MAX_RETRIES",
        "SECURITY__ADMIN_USERNAME", "SECURITY__ADMIN_SECRET",
        "SERVICES__DATABASE_URL",
    ]
    for var in vars_to_clear:
        monkeypatch.delenv(var, raising=False)

    # Use tmp_path as working directory so pydantic-settings won't find the real .env
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("ENCRYPTION_KEY_FILE", str(secrets_dir / "master.key"))
    monkeypatch.setenv("SECURITY__ADMIN_SECRET", "test-secret-key-123456")
    monkeypatch.setenv("PATHS__CREDS_ROOT", str(tmp_path / "credentials"))
    monkeypatch.setenv("SECURITY__ALLOWED_CLIENT_IPS", '["127.0.0.1", "test-ip"]')
    monkeypatch.setenv("SERVICES__DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    yield tmp_path


@pytest.fixture
async def async_db_session():
    """Provides an async DB session using in-memory SQLite for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory

    await engine.dispose()
