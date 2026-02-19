#!/usr/bin/env python3
"""
Утилита для шифрования существующих API ключей.
Использование: python encrypt_keys.py
"""

import os
import json
import sys
from pathlib import Path

# Добавляем путь к app директории
sys.path.append(str(Path(__file__).parent / "app"))

from app import config
from app.security.encryption import encryption_manager


def encrypt_gemini_keys():
    """Шифрует существующие Gemini API ключи."""
    input_file = config.GEMINI_CREDS_DIR

    if not os.path.exists(input_file):
        print(f"Gemini keys file not found: {input_file}")
        return

    try:
        with open(input_file, "r") as f:
            data = json.load(f)

        # Проверяем, уже зашифрованы ли ключи
        if isinstance(data, dict) and "encrypted_keys" in data:
            print("Keys are already encrypted.")
            return

        if not isinstance(data, list):
            print("Invalid format: expected list of strings")
            return

        # Шифруем ключи
        encrypted_keys = []
        for key in data:
            if isinstance(key, str) and key.strip():
                encrypted_key = encryption_manager.encrypt_data(key.strip())
                encrypted_keys.append(encrypted_key)

        # Сохраняем в новом формате
        encrypted_data = {
            "encrypted_keys": encrypted_keys,
            "metadata": {
                "encrypted": True,
                "version": "1.0",
                "original_count": len(data),
            },
        }

        # Создаём бэкап
        backup_file = f"{input_file}.backup"
        with open(backup_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Created backup: {backup_file}")

        # Сохраняем зашифрованные данные
        with open(input_file, "w") as f:
            json.dump(encrypted_data, f, indent=2)

        print(f"Successfully encrypted {len(encrypted_keys)} Gemini keys")
        print("Original keys saved to backup file")

    except Exception as e:
        print(f"Failed to encrypt Gemini keys: {e}")


def main():
    print("=== Encryption Utility ===")
    print("This utility will encrypt existing API keys for security.")
    print("A backup will be created automatically.")
    print()

    response = input("Do you want to continue? (y/N): ")
    if response.lower() not in ["y", "yes"]:
        print("Aborted.")
        return

    encrypt_gemini_keys()
    print("\nEncryption completed.")


if __name__ == "__main__":
    main()
