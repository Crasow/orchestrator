import time
import asyncio
import logging
from typing import Dict, Optional
import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)

class RedisStatsService:
    def __init__(self):
        # Инициализируем соединение с Redis
        # decode_responses=True позволяет получать строки вместо байтов
        self.redis = redis.from_url(settings.services.redis_url, decode_responses=True)
        self.start_time = time.time()

    async def record_request(
        self, 
        provider: str, 
        model: str, 
        key_id: str, 
        status_code: int, 
        latency: float
    ):
        """
        Записывает статистику запроса в Redis.
        Использует pipeline для атомарности и скорости (один сетевой запрос вместо пяти).
        """
        try:
            async with self.redis.pipeline() as pipe:
                # 1. Общие счетчики
                pipe.incr("global:requests")
                if status_code >= 400:
                    pipe.incr("global:errors")
                
                # 2. Сохраняем идентификатор ключа в список известных ключей
                # known_keys:gemini или known_keys:vertex
                pipe.sadd(f"known_keys:{provider}", key_id)

                # 3. Статистика по конкретному ключу
                # stats:key:{key_id}:total -> +1
                base_key = f"stats:key:{key_id}"
                pipe.incr(f"{base_key}:total")
                
                # stats:key:{key_id}:{status_code} -> +1 (например, stats:key:xyz:200)
                pipe.incr(f"{base_key}:{status_code}")
                
                if status_code >= 400:
                    pipe.incr(f"{base_key}:errors")

                # Опционально: можно хранить latency, но в Redis это сложнее.
                # Пока пропустим для простоты, или можно хранить сумму и делить на total.
                pipe.incrbyfloat(f"{base_key}:latency_sum", latency)
                
                # Выполняем все команды разом
                await pipe.execute()
                
        except Exception as e:
            # Не роняем прод, если метрики не записались
            logger.error(f"Failed to record stats to Redis: {e}")

    async def get_stats(self) -> dict:
        """Собирает полную статистику из Redis"""
        try:
            # Получаем общие данные
            total_req = int(await self.redis.get("global:requests") or 0)
            total_err = int(await self.redis.get("global:errors") or 0)
            
            # Получаем списки известных ключей
            gemini_keys = await self.redis.smembers("known_keys:gemini")
            vertex_projects = await self.redis.smembers("known_keys:vertex")
            
            all_keys_data = {}

            # Собираем данные по каждому ключу Gemini
            for key in gemini_keys:
                all_keys_data[key] = await self._get_key_stats(key, "gemini")

            # Собираем данные по каждому проекту Vertex
            for proj in vertex_projects:
                all_keys_data[proj] = await self._get_key_stats(proj, "vertex")

            uptime = time.time() - self.start_time

            return {
                "uptime_seconds": round(uptime, 2),
                "total_requests": total_req,
                "total_errors": total_err,
                "error_rate": round((total_err / total_req * 100), 2) if total_req > 0 else 0,
                "keys_usage": all_keys_data
            }
        except Exception as e:
            logger.error(f"Failed to get stats from Redis: {e}")
            return {"error": str(e)}

    async def _get_key_stats(self, key_id: str, provider: str) -> dict:
        """Вспомогательный метод для чтения статистики по одному ключу"""
        base_key = f"stats:key:{key_id}"
        
        # Запрашиваем основные метрики
        total = int(await self.redis.get(f"{base_key}:total") or 0)
        errors = int(await self.redis.get(f"{base_key}:errors") or 0)
        latency_sum = float(await self.redis.get(f"{base_key}:latency_sum") or 0.0)
        
        # Получаем разбивку по кодам ответов
        # Ищем ключи вида stats:key:{key_id}:200, stats:key:{key_id}:429...
        # В продакшене лучше использовать HASH (hgetall), но для наглядности так
        # Чтобы не сканировать весь Redis, просто вернем основные.
        # Если нужна детализация по кодам, лучше использовать Redis Hash для каждого ключа.
        
        return {
            "provider": provider,
            "total_requests": total,
            "total_errors": errors,
            "avg_latency": round(latency_sum / total, 4) if total > 0 else 0,
            # Можно допилить получение кодов
        }

# Создаем глобальный инстанс
stats_service = RedisStatsService()
