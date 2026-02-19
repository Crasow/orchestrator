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

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "unavailable",
        "gemini_keys": state.gemini_rotator.key_count,
        "vertex_credentials": state.vertex_rotator.credential_count,
    }

# --- ROUTERS ---
app.include_router(admin.router)
app.include_router(proxy.router)
