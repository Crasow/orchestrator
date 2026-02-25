import os
import logging
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import ensure_directories, settings
from app.core.logging import setup_logging
from app.core import state
from app.api import admin, proxy
from app.db import async_engine, async_session_factory, Base
from app.services import statistics
from app.services.statistics import StatsService
from app.services.rotators.gemini import GeminiRotator
from app.services.rotators.vertex import VertexRotator

# --- LOGGING ---
setup_logging()
logger = logging.getLogger("orchestrator")


# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()

    # Create DB tables (dev convenience; in prod use alembic upgrade head)
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # Init rotators (after ensure_directories so credential dirs exist)
    state.gemini_rotator = GeminiRotator()
    state.vertex_rotator = VertexRotator()

    # Init stats service
    statistics.stats_service = StatsService(async_session_factory)

    state.http_client = httpx.AsyncClient(
        timeout=120.0, limits=httpx.Limits(max_keepalive_connections=50)
    )
    logger.info("Orchestrator is ready")
    yield

    if state.http_client:
        await state.http_client.aclose()
    await async_engine.dispose()
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

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HEALTH ---
@app.get("/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    from sqlalchemy import text as sa_text

    db_ok = False
    try:
        async with async_engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    gemini_keys = state.gemini_rotator.key_count if state.gemini_rotator else 0
    vertex_creds = state.vertex_rotator.credential_count if state.vertex_rotator else 0
    has_keys = gemini_keys > 0 or vertex_creds > 0

    if db_ok and has_keys:
        health_status = "healthy"
    elif db_ok:
        health_status = "degraded"  # DB ok but no keys loaded
    else:
        health_status = "unhealthy"

    return {
        "status": health_status,
        "database": "connected" if db_ok else "unavailable",
        "gemini_keys": gemini_keys,
        "vertex_credentials": vertex_creds,
    }

# --- ROUTERS ---
app.include_router(admin.router)
app.include_router(proxy.router)
