import os
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

logger = logging.getLogger("orchestrator.audit")


@dataclass
class AuditEvent:
    timestamp: str
    event_type: str
    client_ip: str
    user_agent: str
    endpoint: str
    method: str
    status_code: int
    response_time: float
    request_size: int
    response_size: int
    user_id: Optional[str] = None
    error_message: Optional[str] = None


class SecurityAuditor:
    def __init__(self):
        self._events: List[AuditEvent] = []
        self._max_events = int(os.environ.get("AUDIT_MAX_EVENTS", "10000"))
        self._log_file = os.environ.get("AUDIT_LOG_FILE", "/app/logs/audit.log")
        os.makedirs(os.path.dirname(self._log_file), exist_ok=True)

    def log_event(self, event: AuditEvent):
        """Логирует событие аудита."""
        self._events.append(event)

        # Ограничиваем количество событий в памяти
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

        # Записываем в лог-файл
        try:
            log_entry = json.dumps(event.__dict__, ensure_ascii=False)
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def get_events_by_timeframe(self, hours: int = 24) -> List[AuditEvent]:
        """Возвращает события за последние N часов."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            event
            for event in self._events
            if datetime.fromisoformat(event.timestamp) >= cutoff_time
        ]

    def get_failed_requests(self, hours: int = 24) -> List[AuditEvent]:
        """Возвращает неудачные запросы за последние N часов."""
        return [
            event
            for event in self.get_events_by_timeframe(hours)
            if event.status_code >= 400
        ]

    def get_suspicious_activity(self, hours: int = 1) -> List[Dict[str, Any]]:
        """Анализирует подозрительную активность."""
        events = self.get_events_by_timeframe(hours)
        suspicious = []

        # Много запросов от одного IP
        ip_requests: Dict[str, int] = {}
        for event in events:
            ip_requests[event.client_ip] = ip_requests.get(event.client_ip, 0) + 1

        threshold = int(os.environ.get("SUSPICIOUS_REQUEST_THRESHOLD", "100"))
        for ip, count in ip_requests.items():
            if count > threshold:
                suspicious.append(
                    {
                        "type": "high_frequency_requests",
                        "ip": ip,
                        "count": count,
                        "threshold": threshold,
                    }
                )

        # Много ошибок аутентификации
        auth_errors = [
            event
            for event in events
            if event.status_code == 401 and event.error_message
        ]

        if len(auth_errors) > 10:
            suspicious.append(
                {
                    "type": "authentication_errors",
                    "count": len(auth_errors),
                    "events": auth_errors[:5],  # Первые 5 событий
                }
            )

        return suspicious

    def cleanup_old_events(self, days: int = 30):
        """Очищает старые события."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        self._events = [
            event
            for event in self._events
            if datetime.fromisoformat(event.timestamp) >= cutoff_time
        ]
        logger.info(f"Cleaned up events older than {days} days")


# Глобальный экземпляр для использования в приложении
security_auditor = SecurityAuditor()
