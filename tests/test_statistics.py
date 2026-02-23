import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base, ApiKey, Model, Request
from app.services.statistics import StatsService


# Re-use async_db_session from conftest.py as db_session
@pytest.fixture
def db_session(async_db_session):
    return async_db_session


@pytest.fixture
def stats_service(db_session):
    """StatsService with in-memory DB."""
    return StatsService(db_session)


@pytest.mark.asyncio
async def test_record_request_inserts_data(stats_service, db_session):
    """Test that record_request creates an api_key, model, and request row."""
    await stats_service.record_request(
        provider="gemini",
        model="gemini-pro",
        key_id="test-key-123",
        status_code=200,
        latency_ms=500,
    )

    async with db_session() as session:
        # Check request was created
        result = await session.execute(select(Request))
        requests = result.scalars().all()
        assert len(requests) == 1
        assert requests[0].provider == "gemini"
        assert requests[0].status_code == 200
        assert requests[0].latency_ms == 500

        # Check api_key was created
        result = await session.execute(select(ApiKey))
        keys = result.scalars().all()
        assert len(keys) == 1
        assert keys[0].key_id == "test-key-123"

        # Check model was created
        result = await session.execute(select(Model))
        models = result.scalars().all()
        assert len(models) == 1
        assert models[0].name == "gemini-pro"


@pytest.mark.asyncio
async def test_record_request_reuses_existing_key_and_model(stats_service, db_session):
    """Test that record_request reuses existing api_key and model rows."""
    await stats_service.record_request(
        provider="gemini", model="gemini-pro", key_id="key-1",
        status_code=200, latency_ms=100,
    )
    await stats_service.record_request(
        provider="gemini", model="gemini-pro", key_id="key-1",
        status_code=200, latency_ms=200,
    )

    async with db_session() as session:
        result = await session.execute(select(Request))
        assert len(result.scalars().all()) == 2

        result = await session.execute(select(ApiKey))
        assert len(result.scalars().all()) == 1

        result = await session.execute(select(Model))
        assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_get_stats(stats_service):
    """Test aggregated stats query."""
    await stats_service.record_request(
        provider="gemini", model="m", key_id="k", status_code=200, latency_ms=100,
    )
    await stats_service.record_request(
        provider="gemini", model="m", key_id="k", status_code=200, latency_ms=200,
    )
    await stats_service.record_request(
        provider="gemini", model="m", key_id="k", status_code=500, latency_ms=300,
        is_error=True,
    )

    stats = await stats_service.get_stats(hours=24)

    assert stats["total_requests"] == 3
    assert stats["total_errors"] == 1
    assert stats["error_rate"] == pytest.approx(33.33, rel=0.01)
    assert stats["avg_latency_ms"] == pytest.approx(200.0, rel=0.01)


@pytest.mark.asyncio
async def test_get_stats_filters_by_provider(stats_service):
    """Test stats filtering by provider."""
    await stats_service.record_request(
        provider="gemini", model="m", key_id="k1", status_code=200, latency_ms=100,
    )
    await stats_service.record_request(
        provider="vertex", model="m", key_id="k2", status_code=200, latency_ms=200,
    )

    gemini_stats = await stats_service.get_stats(hours=24, provider="gemini")
    assert gemini_stats["total_requests"] == 1

    vertex_stats = await stats_service.get_stats(hours=24, provider="vertex")
    assert vertex_stats["total_requests"] == 1


@pytest.mark.asyncio
async def test_get_stats_empty(stats_service):
    """Test stats with no data."""
    stats = await stats_service.get_stats(hours=24)
    assert stats["total_requests"] == 0
    assert stats["total_errors"] == 0
    assert stats["error_rate"] == 0


@pytest.mark.asyncio
async def test_get_requests_log(stats_service):
    """Test request log with pagination."""
    for i in range(5):
        await stats_service.record_request(
            provider="gemini",
            model="gemini-pro",
            key_id=f"key-{i}",
            status_code=200 if i < 3 else 500,
            latency_ms=100 + i * 10,
            is_error=i >= 3,
        )

    log = await stats_service.get_requests_log(limit=3, offset=0)
    assert log["total"] == 5
    assert len(log["requests"]) == 3

    # Test errors only
    log_errors = await stats_service.get_requests_log(errors_only=True)
    assert log_errors["total"] == 2
    assert all(r["is_error"] for r in log_errors["requests"])


@pytest.mark.asyncio
async def test_get_model_stats(stats_service):
    """Test per-model statistics."""
    await stats_service.record_request(
        provider="gemini", model="gemini-pro", key_id="k",
        status_code=200, latency_ms=100,
        total_tokens=1000, prompt_tokens=500, candidates_tokens=500,
    )
    await stats_service.record_request(
        provider="gemini", model="gemini-pro", key_id="k",
        status_code=200, latency_ms=200,
        total_tokens=2000, prompt_tokens=1000, candidates_tokens=1000,
    )
    await stats_service.record_request(
        provider="gemini", model="gemini-flash", key_id="k",
        status_code=200, latency_ms=50,
        total_tokens=500, prompt_tokens=250, candidates_tokens=250,
    )

    result = await stats_service.get_model_stats(hours=24)
    assert len(result["models"]) == 2

    # gemini-pro should be first (more requests)
    pro = result["models"][0]
    assert pro["name"] == "gemini-pro"
    assert pro["total_requests"] == 2
    assert pro["total_tokens"] == 3000


@pytest.mark.asyncio
async def test_cleanup(stats_service):
    """Test that cleanup removes old records."""
    await stats_service.record_request(
        provider="gemini", model="m", key_id="k", status_code=200, latency_ms=100,
    )

    # Cleanup records older than 30 days (should delete nothing since record is fresh)
    result = await stats_service.cleanup(days=30)
    assert result["deleted"] == 0


@pytest.mark.asyncio
async def test_record_request_error_handling(stats_service):
    """Test that record_request does not raise on errors."""
    # Deliberately break the session factory
    stats_service._session_factory = MagicMock(side_effect=Exception("DB error"))

    # Should not raise
    await stats_service.record_request(
        provider="gemini", model="model", key_id="key",
        status_code=200, latency_ms=100,
    )
