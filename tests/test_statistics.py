import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.statistics import RedisStatsService

@pytest.fixture
def mock_redis_client():
    """Возвращает мок клиента Redis."""
    mock = AsyncMock()
    # pipeline() - это обычный метод (не корутина), который возвращает контекстный менеджер
    mock.pipeline = MagicMock() 
    return mock

@pytest.fixture
def stats_service(mock_redis_client):
    """Создает экземпляр сервиса с замоканным Redis."""
    with patch("app.services.statistics.redis.from_url", return_value=mock_redis_client):
        service = RedisStatsService()
        yield service

@pytest.mark.asyncio
async def test_record_request(stats_service, mock_redis_client):
    # Настраиваем мок для pipeline
    mock_pipeline = AsyncMock()
    # Контекстный менеджер pipeline
    mock_pipeline.__aenter__.return_value = mock_pipeline
    mock_pipeline.__aexit__.return_value = None
    
    mock_redis_client.pipeline.return_value = mock_pipeline
    
    await stats_service.record_request(
        provider="gemini",
        model="gemini-pro",
        key_id="test-key-123",
        status_code=200,
        latency=0.5
    )
    
    # Проверяем вызовы
    assert mock_pipeline.incr.call_count >= 2
    mock_pipeline.sadd.assert_called_with("known_keys:gemini", "test-key-123")
    mock_pipeline.execute.assert_called_once()

@pytest.mark.asyncio
async def test_record_request_error(stats_service, mock_redis_client):
    mock_pipeline = AsyncMock()
    mock_pipeline.__aenter__.return_value = mock_pipeline
    mock_redis_client.pipeline.return_value = mock_pipeline
    
    # Эмулируем ошибку
    mock_pipeline.execute.side_effect = Exception("Redis error")
    
    # Не должно выбросить исключение
    await stats_service.record_request("gemini", "model", "key", 200, 0.1)

@pytest.mark.asyncio
async def test_get_stats(stats_service, mock_redis_client):
    # Настраиваем ответы Redis
    async def mock_get(key):
        data = {
            "global:requests": "100",
            "global:errors": "5",
            "stats:key:k1:total": "50",
            "stats:key:k1:errors": "0",
            "stats:key:k1:latency_sum": "10.0",
            "stats:key:p1:total": "50",
            "stats:key:p1:errors": "5",
            "stats:key:p1:latency_sum": "20.0"
        }
        return data.get(key)
    
    mock_redis_client.get.side_effect = mock_get
    
    async def mock_smembers(key):
        data = {
            "known_keys:gemini": {"k1"},
            "known_keys:vertex": {"p1"}
        }
        return data.get(key, set())

    mock_redis_client.smembers.side_effect = mock_smembers
    
    stats = await stats_service.get_stats()
    
    assert stats["total_requests"] == 100
    assert stats["total_errors"] == 5
    assert "k1" in stats["keys_usage"]
    assert stats["keys_usage"]["k1"]["total_requests"] == 50
    assert stats["keys_usage"]["k1"]["avg_latency"] == 0.2
