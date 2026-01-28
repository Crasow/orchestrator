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
        """Получает или создаёт мастер-ключ для шифрования."""
        key_file = os.environ.get("ENCRYPTION_KEY_FILE", "/app/secrets/master.key")

        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Failed to read encryption key: {e}")

        # Создаём новый ключ
        key = Fernet.generate_key()
        try:
            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, "wb") as f:
                f.write(key)
            os.chmod(key_file, 0o600)  # Только для владельца
            logger.info(f"Created new encryption key at {key_file}")
        except Exception as e:
            logger.warning(f"Failed to save encryption key: {e}")

        return key

    def encrypt_data(self, data: str) -> str:
        """Шифрует строковые данные."""
        try:
            encrypted = self._cipher.encrypt(data.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt_data(self, encrypted_data: str) -> str:
        """Расшифровывает строковые данные."""
        try:
            encrypted_bytes = base64.b64decode(encrypted_data.encode())
            decrypted = self._cipher.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def encrypt_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Шифрует учётные данные в словаре."""
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
        """Расшифровывает учётные данные в словаре."""
        decrypted = {}
        for key, value in encrypted_credentials.items():
            if isinstance(value, str) and self._is_sensitive_field(key):
                decrypted[key] = self.decrypt_data(value)
            else:
                decrypted[key] = value
        return decrypted

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Определяет, является ли поле чувствительным."""
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


# Глобальный экземпляр для использования в приложении
encryption_manager = EncryptionManager()
