import os
import json
import logging
from typing import List, Optional

from app.config import settings
from app.security.encryption import encryption_manager

logger = logging.getLogger("orchestrator.gemini")


class GeminiRotator:
    def __init__(self):
        self._keys: List[str] = []
        self._current_index = 0
        self.load_keys()

    def load_keys(self):
        filepath = settings.paths.gemini_keys_file
        if not os.path.exists(filepath):
            logger.warning(f"Gemini keys file not found: {filepath}")
            self._keys = []
            return

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            # Проверяем, зашифрованы ли данные
            if isinstance(data, dict) and "encrypted_keys" in data:
                # Расшифровываем ключи
                encrypted_keys = data["encrypted_keys"]
                if isinstance(encrypted_keys, list):
                    self._keys = []
                    for encrypted_key in encrypted_keys:
                        try:
                            decrypted_key = encryption_manager.decrypt_data(
                                encrypted_key
                            )
                            self._keys.append(decrypted_key)
                        except Exception as e:
                            logger.error(f"Failed to decrypt key: {e}")
                    logger.info(f"Loaded and decrypted {len(self._keys)} Gemini keys.")
                else:
                    logger.error("Encrypted Gemini keys file format error")
            elif isinstance(data, list):
                # Незащищённый формат - для обратной совместимости
                self._keys = [k for k in data if isinstance(k, str) and k.strip()]
                logger.warning(
                    f"Loaded {len(self._keys)} unencrypted Gemini keys. Consider encrypting them."
                )
            else:
                logger.error(
                    "Gemini keys file format error: expected list of strings or encrypted format"
                )
        except Exception as e:
            logger.error(f"Failed to load Gemini keys: {e}")

    def get_next_key(self) -> Optional[str]:
        if not self._keys:
            return None
        key = self._keys[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._keys)
        return key

    def reload(self):
        self.load_keys()
