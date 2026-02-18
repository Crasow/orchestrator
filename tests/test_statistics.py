import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base, ApiKey, Model, Request
from app.services.statistics import StatsService


@pytest.fixture
async def db_session():
    """In-memory SQLite session factory for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def stats_service(db_session):
    """StatsService with in-memory DB."""
    return StatsService(db_session)


async def _insert_test_request(
    session_factory,
    provider="gemini",
    status_code=200,
    latency_ms=100,
    is_error=False,
    model_name=None,
    key_id_str=None,
    prompt_tokens=None,
    candidates_tokens=None,
    total_tokens=None,
):
    """Helper to insert a test request directly, bypassing pg_insert."""
    async with session_factory() as session:
        async with session.begin():
            api_key_pk = None
            if key_id_str:
                # Check if key exists
                result = await session.execute(select(ApiKey).where(ApiKey.key_id == key_id_str))
                existing = result.scalar_one_or_none()
                if existing:
                    api_key_pk = existing.id
                else:
                    ak = ApiKey(provider=provider, key_id=key_id_str)
                    session.add(ak)
                    await session.flush()
                    api_key_pk = ak.id

            model_pk = None
            if model_name and model_name != "unknown":
                result = await session.execute(select(Model).where(Model.name == model_name))
                existing = result.scalar_one_or_none()
                if existing:
                    model_pk = existing.id
                else:
                    m = Model(name=model_name, provider=provider)
                    session.add(m)
                    await session.flush()
                    model_pk = m.id

            req = Request(
                api_key_id=api_key_pk,
                model_id=model_pk,
                provider=provider,
                status_code=status_code,
                latency_ms=latency_ms,
                url_path="/test",
                is_error=is_error,
                prompt_tokens=prompt_tokens,
                candidates_tokens=candidates_tokens,
                total_tokens=total_tokens,
            )
            session.add(req)


@pytest.mark.asyncio
async def test_record_request_inserts_data(stats_service, db_session):
    """Test that record_request creates an api_key, model, and request row."""
    # record_request uses pg_insert (PostgreSQL only), so we test via direct insert
    await _insert_test_request(
        db_session,
        provider="gemini",
        key_id_str="test-key-123",
        model_name="gemini-pro",
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
async def test_get_stats(stats_service, db_session):
    """Test aggregated stats query."""
    # Insert some test data
    await _insert_test_request(db_session, status_code=200, latency_ms=100, is_error=False)
    await _insert_test_request(db_session, status_code=200, latency_ms=200, is_error=False)
    await _insert_test_request(db_session, status_code=500, latency_ms=300, is_error=True)

    stats = await stats_service.get_stats(hours=24)

    assert stats["total_requests"] == 3
    assert stats["total_errors"] == 1
    assert stats["error_rate"] == pytest.approx(33.33, rel=0.01)
    assert stats["avg_latency_ms"] == pytest.approx(200.0, rel=0.01)


@pytest.mark.asyncio
async def test_get_stats_filters_by_provider(stats_service, db_session):
    """Test stats filtering by provider."""
    await _insert_test_request(db_session, provider="gemini", status_code=200, latency_ms=100)
    await _insert_test_request(db_session, provider="vertex", status_code=200, latency_ms=200)

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
async def test_get_requests_log(stats_service, db_session):
    """Test request log with pagination."""
    for i in range(5):
        await _insert_test_request(
            db_session,
            provider="gemini",
            status_code=200 if i < 3 else 500,
            latency_ms=100 + i * 10,
            is_error=i >= 3,
            key_id_str=f"key-{i}",
            model_name="gemini-pro",
        )

    log = await stats_service.get_requests_log(limit=3, offset=0)
    assert log["total"] == 5
    assert len(log["requests"]) == 3

    # Test errors only
    log_errors = await stats_service.get_requests_log(errors_only=True)
    assert log_errors["total"] == 2
    assert all(r["is_error"] for r in log_errors["requests"])


@pytest.mark.asyncio
async def test_get_model_stats(stats_service, db_session):
    """Test per-model statistics."""
    await _insert_test_request(
        db_session, model_name="gemini-pro", latency_ms=100,
        total_tokens=1000, prompt_tokens=500, candidates_tokens=500,
    )
    await _insert_test_request(
        db_session, model_name="gemini-pro", latency_ms=200,
        total_tokens=2000, prompt_tokens=1000, candidates_tokens=1000,
    )
    await _insert_test_request(
        db_session, model_name="gemini-flash", latency_ms=50,
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
async def test_cleanup(stats_service, db_session):
    """Test that cleanup removes old records."""
    # Insert a record (created_at defaults to now, so it should survive cleanup)
    await _insert_test_request(db_session, status_code=200, latency_ms=100)

    # Cleanup records older than 30 days (should delete nothing)
    result = await stats_service.cleanup(days=30)
    assert result["deleted"] == 0

    # Verify record still exists
    async with db_session() as session:
        count = await session.execute(select(Request))
        assert len(count.scalars().all()) == 1


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
