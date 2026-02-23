from __future__ import annotations

import httpx
from app.services.rotators.vertex import VertexRotator
from app.services.rotators.gemini import GeminiRotator

# Initialized in lifespan (app/main.py), NOT at import time
vertex_rotator: VertexRotator | None = None
gemini_rotator: GeminiRotator | None = None
http_client: httpx.AsyncClient | None = None
