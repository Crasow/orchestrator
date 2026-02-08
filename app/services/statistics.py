import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List
import asyncio

@dataclass
class ModelStats:
    requests: int = 0
    errors: int = 0
    total_latency: float = 0.0
    last_access: float = 0.0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.requests if self.requests > 0 else 0.0

class StatisticsService:
    def __init__(self):
        # Общая статистика
        self.total_requests = 0
        self.total_errors = 0
        self.start_time = time.time()
        
        # Статистика по провайдерам и моделям
        # Структура: self.models[provider][model_name] = ModelStats
        self.models: Dict[str, Dict[str, ModelStats]] = defaultdict(lambda: defaultdict(ModelStats))
        
        # Для расчета RPS (запросы за последнюю минуту)
        self._requests_window = deque()
        self._window_size = 60  # секунды

    async def record_request(self, provider: str, model: str, status_code: int, latency: float):
        """Асинхронная запись метрики, чтобы не блочить поток"""
        current_time = time.time()
        
        # Обновляем общие счетчики
        self.total_requests += 1
        if status_code >= 400:
            self.total_errors += 1
            
        # Очистка окна RPS (удаляем старые записи)
        while self._requests_window and self._requests_window[0] < current_time - self._window_size:
            self._requests_window.popleft()
        self._requests_window.append(current_time)

        # Статистика по конкретной модели
        stats = self.models[provider][model]
        stats.requests += 1
        stats.total_latency += latency
        stats.last_access = current_time
        if status_code >= 400:
            stats.errors += 1

    def get_stats(self) -> dict:
        """Получение сводной статистики"""
        current_time = time.time()
        uptime = current_time - self.start_time
        
        # Очистка окна для точного RPS при чтении
        while self._requests_window and self._requests_window[0] < current_time - self._window_size:
            self._requests_window.popleft()
            
        rps = len(self._requests_window) / self._window_size if uptime > self._window_size else len(self._requests_window) / uptime

        return {
            "uptime_seconds": round(uptime, 2),
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": round((self.total_errors / self.total_requests * 100), 2) if self.total_requests > 0 else 0,
            "current_rps": round(rps, 2),
            "providers": {
                provider: {
                    model: {
                        "requests": data.requests,
                        "errors": data.errors,
                        "avg_latency_ms": round(data.avg_latency * 1000, 2),
                        "last_access_ago": round(current_time - data.last_access, 1) if data.last_access > 0 else None
                    }
                    for model, data in models_data.items()
                }
                for provider, models_data in self.models.items()
            }
        }

# Глобальный инстанс
stats_service = StatisticsService()
