import os
import base64
import logging
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet

logger = logging.getLogger("orchestrator.security")


class EncryptionManager:
    def __init__(self, master_key: Optional[str] = None):
        self._master_key = master_key or self._get_or_create_master_key()
        self._cipher = Fernet(self._master_key)

    def _get_or_create_master_key(self) -> bytes:
        """Get or create the master encryption key."""
        key_file = os.environ.get("ENCRYPTION_KEY_FILE", "/app/secrets/master.key")

        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Failed to read encryption key: {e}")

        # Generate new key
        key = Fernet.generate_key()
        try:
            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, "wb") as f:
                f.write(key)
            os.chmod(key_file, 0o600)  # Owner only
            logger.info(f"Created new encryption key at {key_file}")
        except Exception as e:
            logger.warning(f"Failed to save encryption key: {e}")

        return key

    def encrypt_data(self, data: str) -> str:
        """Encrypt a string value."""
        try:
            encrypted = self._cipher.encrypt(data.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt_data(self, encrypted_data: str) -> str:
        """Decrypt a string value."""
        try:
            encrypted_bytes = base64.b64decode(encrypted_data.encode())
            decrypted = self._cipher.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def encrypt_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt sensitive fields in a credentials dictionary."""
        encrypted = {}
        for key, value in credentials.items():
            if isinstance(value, str) and self._is_sensitive_field(key):
                encrypted[key] = self.encrypt_data(value)
            else:
                encrypted[key] = value
        return encrypted

    def decrypt_credentials(
        self, encrypted_credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Decrypt sensitive fields in a credentials dictionary."""
        decrypted = {}
        for key, value in encrypted_credentials.items():
            if isinstance(value, str) and self._is_sensitive_field(key):
                decrypted[key] = self.decrypt_data(value)
            else:
                decrypted[key] = value
        return decrypted

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Check if a field name matches known sensitive patterns."""
        sensitive_patterns = [
            "key",
            "token",
            "secret",
            "password",
            "credential",
            "private_key",
            "api_key",
            "auth",
        ]
        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in sensitive_patterns)


# Lazy singleton — initialized on first access, not at import time
_encryption_manager: EncryptionManager | None = None


def __getattr__(name: str):
    global _encryption_manager
    if name == "encryption_manager":
        if _encryption_manager is None:
            _encryption_manager = EncryptionManager()
        return _encryption_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
