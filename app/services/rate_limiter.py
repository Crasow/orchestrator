import asyncio
import logging
import time

logger = logging.getLogger("orchestrator.rate_limiter")


class KeyRateLimiter:
    """Per-key semaphore + auto-disable for exhausted keys."""

    def __init__(self, concurrency: int = 1):
        self._concurrency = concurrency
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._disabled_until: dict[str, float] = {}

    def _get_semaphore(self, key: str) -> asyncio.Semaphore:
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(self._concurrency)
        return self._semaphores[key]

    def acquire(self, key: str) -> asyncio.Semaphore:
        """Return the semaphore for use as `async with limiter.acquire(key):`."""
        return self._get_semaphore(key)

    def disable_key(self, key: str, duration: float = 86400) -> None:
        until = time.time() + duration
        self._disabled_until[key] = until
        logger.warning(f"Key {key} disabled for {duration}s (until {until:.0f})")

    def is_available(self, key: str) -> bool:
        until = self._disabled_until.get(key)
        if until is None:
            return True
        if time.time() >= until:
            del self._disabled_until[key]
            return True
        return False

    @property
    def available_count(self) -> int:
        """Count of keys that are NOT currently disabled."""
        now = time.time()
        # Clean up expired entries
        expired = [k for k, v in self._disabled_until.items() if now >= v]
        for k in expired:
            del self._disabled_until[k]
        return len(self._semaphores) - len(self._disabled_until)

    def status(self) -> dict:
        now = time.time()
        disabled = {}
        for key, until in self._disabled_until.items():
            remaining = until - now
            if remaining > 0:
                disabled[key] = {"disabled_until": until, "remaining_seconds": int(remaining)}
        return {"disabled_keys": disabled, "total_tracked": len(self._semaphores)}

    def reset_key(self, key: str) -> None:
        self._disabled_until.pop(key, None)
        logger.info(f"Key {key} manually re-enabled")

    def register_key(self, key: str) -> None:
        """Ensure a semaphore exists for this key."""
        self._get_semaphore(key)
