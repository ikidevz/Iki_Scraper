"""
Exponential-backoff retry wrapper.
Wraps any async coroutine; retries on exception up to max_retries.
Strategy: callers pass in a coroutine factory (lambda), get the result.
"""

import asyncio
from ..patterns.logger import AppLogger

log = AppLogger.get()


class RetryPolicy:
    def __init__(self, max_retries: int, base_delay: float):
        self._max = max_retries
        self._base = base_delay

    async def execute(self, coro_fn, label: str = ""):
        last_exc: Exception | None = None
        for attempt in range(self._max + 1):
            try:
                return await coro_fn()
            except Exception as exc:
                last_exc = exc
                if attempt == self._max:
                    break
                wait = self._base * (2 ** attempt)
                log.warning(
                    "Retry %d/%d for %s in %.1fs — %s",
                    attempt + 1, self._max, label, wait, exc
                )
                await asyncio.sleep(wait)
        raise last_exc
