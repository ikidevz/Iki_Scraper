"""Fetches and rotates free proxies with validation and multiple sources."""

import re
import httpx
import asyncio
from typing import Optional, List
from ..config import ScraperConfig
from ..patterns.logger import AppLogger

log = AppLogger.get()


class ProxyManager:
    """Round-robin proxy manager with multiple sources and basic health checking."""

    _SOURCES = [
        # ProxyScrape
        "https://api.proxyscrape.com/v2/?request=displayproxies"
        "&protocol=http&timeout={timeout}&country=all&ssl=all&anonymity=all",

        # Free Proxy List (good alternative)
        "https://www.free-proxy-list.net/",

        # Alternative sources
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]

    def __init__(self, cfg: ScraperConfig):
        self._cfg = cfg
        self._pool: List[str] = []
        self._index = 0
        self._since_refresh = 0
        self._tested_proxies: List[str] = []

    async def _fetch_from_url(self, client: httpx.AsyncClient, url: str) -> List[str]:
        """Fetch proxies from a single source."""
        try:
            r = await client.get(url, timeout=12)
            r.raise_for_status()

            if "proxyscrape.com" in url:
                proxies = [p.strip() for p in r.text.splitlines() if p.strip()]
            elif "free-proxy-list.net" in url:
                proxies = re.findall(
                    r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)', r.text)
            else:
                proxies = [p.strip() for p in r.text.splitlines()
                           if p.strip() and ':' in p]

            log.info(
                f"Fetched {len(proxies)} proxies from {url.split('//')[1].split('/')[0]}")
            return proxies

        except Exception as exc:
            log.warning(f"Failed to fetch from {url}: {exc}")
            return []

    async def _fetch_pool(self) -> List[str]:
        """Fetch from multiple sources and combine."""
        all_proxies = set()

        async with httpx.AsyncClient(timeout=15) as client:
            tasks = [self._fetch_from_url(client, url.format(timeout=self._cfg.proxyscrape_timeout_ms))
                     for url in self._SOURCES]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, list):
                    all_proxies.update(result)

        pool = list(all_proxies)
        log.info(f"Total unique proxies collected: {len(pool)}")
        return pool

    async def _test_proxy(self, proxy: str, timeout: int = 8) -> bool:
        """Quick test if proxy is alive."""
        proxies = {"http://": f"http://{proxy}", "https://": f"http://{proxy}"}
        test_urls = ["https://httpbin.org/ip", "https://api.ipify.org"]

        async with httpx.AsyncClient(proxies=proxies, timeout=timeout) as client:
            for url in test_urls:
                try:
                    r = await client.get(url, timeout=timeout)
                    if r.status_code == 200:
                        return True
                except:
                    continue
        return False

    async def _validate_proxies(self, proxies: List[str], max_test: int = 60) -> List[str]:
        """Test a sample of proxies and keep working ones."""
        if not proxies:
            return []

        to_test = proxies[:max_test]
        log.info(f"Testing {len(to_test)} proxies...")

        tasks = [self._test_proxy(p) for p in to_test]
        results = await asyncio.gather(*tasks)

        working = [proxy for proxy, ok in zip(to_test, results) if ok]
        log.info(f"Working proxies after test: {len(working)}/{len(to_test)}")

        return working

    async def next_proxy(self) -> Optional[dict]:
        if not self._cfg.use_proxies:
            return None

        needs_refresh = (
            not self._tested_proxies or
            self._since_refresh >= self._cfg.proxy_refresh_every
        )

        if needs_refresh:
            log.info("Refreshing proxy pool...")
            raw_pool = await self._fetch_pool()

            if raw_pool:
                self._tested_proxies = await self._validate_proxies(raw_pool)

            self._index = 0
            self._since_refresh = 0

        if not self._tested_proxies:
            log.warning("No working proxies available")
            return None

        # Round-robin
        proxy = self._tested_proxies[self._index % len(self._tested_proxies)]
        self._index += 1
        self._since_refresh += 1

        return {"server": f"http://{proxy}"}
