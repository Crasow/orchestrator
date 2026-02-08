import httpx
from app.services.rotators.vertex import VertexRotator
from app.services.rotators.gemini import GeminiRotator

vertex_rotator = VertexRotator()
gemini_rotator = GeminiRotator()
http_client: httpx.AsyncClient | None = None
