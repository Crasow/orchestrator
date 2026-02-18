import os
import logging
import httpx
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.config import ensure_directories
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

# --- ROUTERS ---
app.include_router(admin.router)
app.include_router(proxy.router)
