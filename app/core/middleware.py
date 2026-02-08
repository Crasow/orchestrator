import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.statistics import stats_service

class StatsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/admin") or request.url.path == "/health":
            return await call_next(request)

        start_time = time.time()
        
        # Выполнение запроса
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            process_time = time.time() - start_time
            
            # Определяем провайдера и модель (упрощенная логика)
            path = request.url.path
            if "projects/" in path:
                provider = "vertex"
                # Пытаемся вытащить модель из пути, например /publishers/google/models/gemini-1.5-pro
                parts = path.split("/")
                try:
                    model_idx = parts.index("models") + 1
                    model = parts[model_idx]
                except (ValueError, IndexError):
                    model = "unknown"
            else:
                provider = "gemini"
                # Обычно /v1beta/models/gemini-pro:generateContent
                parts = path.split("/")
                try:
                    model_idx = parts.index("models") + 1
                    # Может быть 'gemini-pro:generateContent', берем до двоеточия
                    model = parts[model_idx].split(":")[0]
                except (ValueError, IndexError):
                    model = "unknown"

            # Асинхронно обновляем статистику (не блокируем ответ клиенту)
            # В реальном хайлоаде лучше использовать background task, но здесь ок
            await stats_service.record_request(provider, model, status_code, process_time)

        return response
