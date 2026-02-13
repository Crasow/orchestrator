import os
import logging
import httpx
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.config import ensure_directories
from app.core.logging import setup_logging
from app.core import state
from app.api import admin, proxy
from app.core.middleware import StatsMiddleware

# --- LOGGING ---
setup_logging()
logger = logging.getLogger("orchestrator")


# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения.
    При старте: создает каталоги и инициализирует HTTP-клиент.
    При остановке: закрывает HTTP-клиент.
    """
    ensure_directories()
    
    state.http_client = httpx.AsyncClient(
        timeout=120.0, limits=httpx.Limits(max_keepalive_connections=50)
    )
    logger.info("Orchestrator is ready")
    yield
    
    if state.http_client:
        await state.http_client.aclose()
    logger.info("Orchestrator stopped")

# --- APP ---
app = FastAPI(
    lifespan=lifespan,
    title="AI Services Orchestrator",
    description="Secure proxy for Google AI services",
    docs_url="/docs"
    if os.environ.get("ENABLE_DOCS", "false").lower() == "true"
    else None,
)

# --- ROUTERS ---
app.include_router(admin.router)
app.include_router(proxy.router)

