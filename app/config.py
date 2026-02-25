"""
Application Configuration using Pydantic Settings.

This module centralizes all application settings, loading them from environment
variables and/or a .env file. It provides a structured, type-hinted, and
validated way to access configuration.
"""
import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Set, Optional

from pydantic import Field, model_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# Configure logger for this module
logger = logging.getLogger("orchestrator.config")

# --- Core Settings Models ---

class PathSettings(BaseSettings):
    """Defines all directory and file paths used in the application."""
    base_dir: Path = Path(__file__).resolve().parent.parent
    creds_root: Optional[Path] = None

    @model_validator(mode='after')
    def set_dynamic_paths(self) -> 'PathSettings':
        if self.creds_root is None:
            self.creds_root = self.base_dir / "credentials"
        return self
    
    @property
    def vertex_creds_dir(self) -> Path:
        return self.creds_root / "vertex"

    @property
    def gemini_creds_dir(self) -> Path:
        return self.creds_root / "gemini"

    @property
    def gemini_keys_file(self) -> Path:
        return self.gemini_creds_dir / "api_keys.json"


class ServiceSettings(BaseSettings):
    """Configuration for external services."""
    vertex_base_url: str = "https://us-central1-aiplatform.googleapis.com"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    max_retries: int = 10
    database_url: str = "postgresql+asyncpg://orchestrator:orchestrator@postgres:5432/orchestrator"
    stats_retention_days: int = 30
    store_request_bodies: bool = False


class SecuritySettings(BaseSettings):
    """Security-related settings, including secrets and access controls."""
    admin_secret: str = Field("change-me-to-a-random-string", min_length=16)
    admin_username: str = "admin"
    admin_password_hash: str = ""
    # * means all IPs are allowed. Defaulting to * for better out-of-the-box Docker support.
    allowed_client_ips: list[str] = ["*"]
    cors_origins: list[str] = ["*"]
    trust_proxy_headers: bool = False
    cookie_secure: bool = False

    def __init__(self, **values):
        super().__init__(**values)
        if self.allowed_client_ips == ["*"]:
            logger.warning("ALLOWED_CLIENT_IPS is set to *. Proxy endpoints will be accessible to all IPs.")

class Settings(BaseSettings):
    """Main settings aggregator."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra='ignore',  # Ignore extra env vars to allow for nested model population
    )
    
    log_level: str = "INFO"
    paths: PathSettings = Field(default_factory=PathSettings)
    services: ServiceSettings = Field(default_factory=ServiceSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

# --- Singleton Instance ---

@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the application settings.
    Using lru_cache ensures the settings are loaded from the environment only once.
    """
    return Settings()

# --- Directory Initialization ---

def ensure_directories():
    """
    Creates necessary credential directories if they don't exist.
    This function should be called once during application startup.
    """
    settings = get_settings()
    dirs_to_create = [
        settings.paths.creds_root,
        settings.paths.vertex_creds_dir,
        settings.paths.gemini_creds_dir,
    ]
    
    for dir_path in dirs_to_create:
        try:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created directory: {dir_path}")
        except OSError as e:
            logger.error(f"Failed to create directory {dir_path}: {e}")
            raise
            
    # Create an empty template for Gemini keys if the file doesn't exist
    gemini_keys_file = settings.paths.gemini_keys_file
    if not gemini_keys_file.exists():
        try:
            with open(gemini_keys_file, "w") as f:
                f.write("[]")  # Empty JSON list
            logger.warning(f"Created empty template for Gemini keys: {gemini_keys_file}")
        except IOError as e:
            logger.error(f"Failed to create Gemini keys template {gemini_keys_file}: {e}")
            raise

# Module-level convenience instance. Note: this is evaluated once at import time.
# Tests that need different settings should call get_settings.cache_clear() before
# importing modules that depend on this, and set env vars before that import.
settings = get_settings()