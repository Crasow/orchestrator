import os
import glob
import json
import asyncio
import logging
from dataclasses import dataclass
from typing import List
from google.oauth2 import service_account
from google.auth.transport.requests import Request

from app.config import settings

logger = logging.getLogger("orchestrator.vertex")


@dataclass
class VertexCredential:
    project_id: str
    creds: service_account.Credentials
    json_path: str


class VertexRotator:
    def __init__(self):
        self._pool: List[VertexCredential] = []
        self._current_index = 0
        self.load_credentials()

    def load_credentials(self):
        creds_dir = settings.paths.vertex_creds_dir
        files = glob.glob(os.path.join(creds_dir, "*.json"))
        # Исключаем gemini_keys.json, если он лежит в той же папке
        files = [f for f in files if "gemini_keys" not in f]

        new_pool = []

        if not files:
            logger.warning(f"No Vertex credentials found in {creds_dir}")
            return

        for fpath in files:
            try:
                with open(fpath, "r") as f:
                    info = json.load(f)

                # Простейшая проверка, что это Service Account
                if "private_key" not in info or "project_id" not in info:
                    continue

                project_id = info.get("project_id")
                scopes = ["https://www.googleapis.com/auth/cloud-platform"]
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=scopes
                )
                new_pool.append(VertexCredential(project_id, creds, fpath))
            except Exception as e:
                logger.error(f"Failed to load {fpath}: {e}")

        self._pool = new_pool
        logger.info(f"Loaded {len(self._pool)} Vertex credentials.")

    @property
    def credentials(self) -> List[VertexCredential]:
        return list(self._pool)

    @property
    def credential_count(self) -> int:
        return len(self._pool)

    def get_next_credential(self) -> VertexCredential:
        if not self._pool:
            raise RuntimeError("Vertex Credential pool is empty")
        cred = self._pool[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._pool)
        return cred

    async def get_token(self, cred_wrapper: VertexCredential) -> str:
        creds = cred_wrapper.creds
        if not creds.valid:
            await asyncio.to_thread(creds.refresh, Request())
        return creds.token

    def reload(self):
        self.load_credentials()
