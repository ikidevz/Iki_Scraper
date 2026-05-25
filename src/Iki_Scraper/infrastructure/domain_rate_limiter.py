"""
Enforces a minimum gap between requests to the same domain.
Uses asyncio.Lock per domain so concurrent coroutines queue correctly.
0.0 = disabled (pass-through).
"""

import asyncio
import time

from urllib.parse import urlparse
from ..patterns.logger import AppLogger

log = AppLogger.get()


class DomainRateLimiter:
    def __init__(self, min_gap_s: float):
        self._gap = min_gap_s
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc

    async def acquire(self, url: str) -> None:
        if self._gap <= 0:
            return
        domain = self._domain(url)
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()

        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last.get(domain, 0.0)
            wait = self._gap - (now - last)
            if wait > 0:
                log.debug("Rate-limiting %s — waiting %.2fs", domain, wait)
                await asyncio.sleep(wait)
            self._last[domain] = time.monotonic()
