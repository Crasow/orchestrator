import os
import glob
import json
import time
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple
from google.oauth2 import service_account
from google.auth.transport.requests import Request


@dataclass
class VertexCredential:
    project_id: str
    creds: service_account.Credentials
    json_path: str


class CredentialRotator:
    def __init__(self, creds_dir: str):
        self._pool: List[VertexCredential] = []
        self._current_index = 0
        self._load_credentials(creds_dir)

    def _load_credentials(self, directory: str):
        # Ищем все .json файлы в папке
        files = glob.glob(os.path.join(directory, "*.json"))
        if not files:
            raise RuntimeError(f"No JSON credentials found in {directory}")

        for fpath in files:
            try:
                # Загружаем для получения project_id и создания creds
                with open(fpath, "r") as f:
                    info = json.load(f)

                project_id = info.get("project_id")
                # Scopes обязательны для Vertex AI
                scopes = ["https://www.googleapis.com/auth/cloud-platform"]
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=scopes
                )

                self._pool.append(
                    VertexCredential(
                        project_id=project_id, creds=creds, json_path=fpath
                    )
                )
                print(f"[INFO] Loaded credential for project: {project_id}")
            except Exception as e:
                print(f"[ERROR] Failed to load {fpath}: {e}")

        # Если надо будет использовать ключи равномерно
        # random.shuffle(self._pool)

    def get_next_credential(self) -> VertexCredential:
        """Возвращает следующий креденишл по кругу (Round Robin)."""
        if not self._pool:
            raise RuntimeError("Credential pool is empty")

        # Простая ротация. Можно усложнить (пропускать временно забаненные)
        cred = self._pool[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._pool)
        return cred

    def get_token_for_credential(self, cred_wrapper: VertexCredential) -> str:
        """Получает валидный Access Token (обновляет если протух)."""
        creds = cred_wrapper.creds
        if not creds.valid:
            creds.refresh(Request())
        return creds.token
