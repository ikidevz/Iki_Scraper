"""
Single entry point. Wires the full object graph internally.
Callers only need three methods + add_observer() + discover_sitemap().
"""

import asyncio
import json

from pathlib import Path
from typing import Optional
from Iki_Scraper.config import ScraperConfig
from Iki_Scraper.patterns import (
    AppLogger,
    SlowPageObserver,
    EventBus,
    LoggingObserver,
    ScrapeObserver,
    LocalFileRepository,
    SQLiteRepository,
    CompositeRepository,
    OutputRepository,
    ParseStrategyFactory,
    CheckpointStore,
    ChangeDetector,
    RetryPolicy
)
from Iki_Scraper.infrastructure import (
    SitemapDiscovery,
    ProxyManager,
    DomainRateLimiter,
    BrowserContextFactory
)
from Iki_Scraper.core import (
    ScraperOrchestrator,
    StandardScraper
)
import nest_asyncio
nest_asyncio.apply()

log = AppLogger.get()


def _load_urls(path: str) -> list[str]:
    p = Path(path)
    if p.suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(u) for u in data]
        raise ValueError("JSON file must contain a list of URL strings.")
    return [
        line.strip()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


class ScraperFacade:
    def __init__(self, cfg: Optional[ScraperConfig] = None):
        self._cfg = cfg or ScraperConfig()
        self._bus = self._build_bus()
        self._slow = SlowPageObserver(self._cfg.slow_page_threshold_sec)
        self._bus.subscribe(self._slow)
        self._orch = self._build_orchestrator()

    def _build_bus(self) -> EventBus:
        bus = EventBus()
        bus.subscribe(LoggingObserver())
        return bus

    def _build_orchestrator(self) -> ScraperOrchestrator:
        cfg = self._cfg

        # Repository — composite if SQLite enabled, plain file otherwise
        file_repo = LocalFileRepository(cfg.output_dir)
        if cfg.use_sqlite:
            db_repo = SQLiteRepository(cfg.sqlite_path)
            repo: OutputRepository = CompositeRepository(file_repo, db_repo)
        else:
            repo = file_repo

        parser = ParseStrategyFactory.create(cfg)
        proxy_mgr = ProxyManager(cfg)
        rate_lim = DomainRateLimiter(cfg.domain_rate_limit)
        ctx_factory = BrowserContextFactory(cfg)

        checkpoint = CheckpointStore(cfg.output_dir) if cfg.resumable else None
        change_det = ChangeDetector(
            cfg.output_dir) if cfg.skip_unchanged else None
        retry = RetryPolicy(cfg.max_retries, cfg.retry_base_delay_sec) \
            if cfg.max_retries > 0 else None

        scraper = StandardScraper(
            cfg, ctx_factory, proxy_mgr, rate_lim,
            parser, repo, self._bus,
            checkpoint, change_det, retry,
        )
        return ScraperOrchestrator(cfg, scraper, repo, self._bus)

    # ── public API ────────────────────────────────────────────────────────────

    def scrape_one(self, url: str) -> dict:
        return asyncio.run(self._orch.run([url]))

    def scrape_many(self, urls: list[str]) -> dict:
        return asyncio.run(self._orch.run(urls))

    def scrape_file(self, filepath: str) -> dict:
        urls = _load_urls(filepath)
        log.info("Loaded %d URLs from %s", len(urls), filepath)
        return asyncio.run(self._orch.run(urls))

    async def discover_sitemap(self, base_url: str) -> list[str]:
        return await SitemapDiscovery().discover(base_url)

    def scrape_sitemap(self, base_url: str) -> dict:
        urls = asyncio.run(self.discover_sitemap(base_url))
        log.info("Sitemap discovered %d URLs for %s", len(urls), base_url)
        return asyncio.run(self._orch.run(urls))

    def add_observer(self, observer: ScrapeObserver) -> None:
        self._bus.subscribe(observer)

    @property
    def slow_pages(self) -> list[dict]:
        """Feature #9 — list of {url, elapsed_s} for pages above threshold."""
        return self._slow.slow_pages
