import os
import glob
import json
import asyncio
import random
from dataclasses import dataclass
from typing import List, Optional
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
        self._pool_map: dict[
            str, VertexCredential
        ] = {}  # Для быстрого поиска по project_id
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
                if not project_id:
                    print(f"[WARN] No project_id in {fpath}, skipping")
                    continue
                # Scopes обязательны для Vertex AI
                scopes = ["https://www.googleapis.com/auth/cloud-platform"]
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=scopes
                )

                credential = VertexCredential(
                    project_id=project_id, creds=creds, json_path=fpath
                )

                self._pool.append(credential)
                self._pool_map[project_id] = credential  # Сохраняем в мапу

                print(f"[INFO] Loaded credential for project: {project_id}")
            except Exception as e:
                print(f"[ERROR] Failed to load {fpath}: {e}")

        if not self._pool:
            raise RuntimeError("No valid credentials loaded")

        random.shuffle(
            self._pool
        )  # Перемешиваем пул для равномерного распределения нагрузки

    def get_next_credential(self) -> VertexCredential:
        """Возвращает следующий креденишл по кругу (Round Robin)."""
        if not self._pool:
            raise RuntimeError("Credential pool is empty")

        # Простая ротация. Можно усложнить (пропускать временно забаненные)
        cred = self._pool[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._pool)
        return cred

    def get_credential_by_project_id(
        self, project_id: str
    ) -> Optional[VertexCredential]:
        """Возвращает конкретный креденишл по ID проекта."""
        return self._pool_map.get(project_id)

    async def get_token_for_credential_async(
        self, cred_wrapper: VertexCredential
    ) -> str:
        """Получает валидный Access Token (обновляет если протух)."""
        creds = cred_wrapper.creds
        if not creds.valid:
            await asyncio.to_thread(creds.refresh, Request())
        return creds.token
