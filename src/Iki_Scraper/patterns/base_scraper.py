import abc
import time
import random

from typing import Optional
from datetime import datetime, timezone
from playwright.async_api import Page, Browser, BrowserContext

from ..config import ScraperConfig
from ..patterns.logger import AppLogger
from ..patterns.parse_strategy import ParseStrategy
from ..patterns.repository import OutputRepository
from ..patterns.observer import EventBus
from ..patterns.change_detector import ChangeDetector
from ..patterns.checkpoint import CheckpointStore
from ..patterns.retry_policy import RetryPolicy

from ..infrastructure.context_factory import BrowserContextFactory
from ..infrastructure.domain_rate_limiter import DomainRateLimiter
from ..infrastructure.human_behavior import HumanBehaviour
from ..infrastructure.proxy_manager import ProxyManager

log = AppLogger.get()


class BaseScraper(abc.ABC):
    """
    Template Method: scrape_pipeline() is the fixed algorithm.
    Hooks: before_navigate · after_navigate · after_extract · collect_pages
    """

    def __init__(
        self,
        cfg:         ScraperConfig,
        ctx_factory: BrowserContextFactory,
        proxy_mgr:   ProxyManager,
        rate_lim:    DomainRateLimiter,
        parser:      ParseStrategy,
        repo:        OutputRepository,
        bus:         EventBus,
        checkpoint:  Optional[CheckpointStore] = None,
        change_det:  Optional[ChangeDetector] = None,
        retry:       Optional[RetryPolicy] = None,
    ):
        self._cfg = cfg
        self._ctx_factory = ctx_factory
        self._proxy_mgr = proxy_mgr
        self._rate_lim = rate_lim
        self._parser = parser
        self._repo = repo
        self._bus = bus
        self._checkpoint = checkpoint
        self._change_det = change_det
        self._retry = retry

    # ── hooks ─────────────────────────────────────────────────────────────────

    async def before_navigate(self, page: Page, url: str) -> None:
        """Override: inject cookies, localStorage, perform login."""
        pass

    async def after_navigate(self, page: Page, url: str) -> None:
        """Override: wait for SPA selector, check for CAPTCHA."""
        pass

    async def after_extract(self, page: Page, html: str, url: str) -> None:
        """Override: screenshot, download assets, trigger side-effects."""
        pass

    async def collect_pages(self, page: Page, url: str) -> list[str]:
        """
        Feature #4 — Pagination hook.
        Override to return additional URLs discovered on this page
        (e.g. 'Next page' links, paginated API endpoints).
        Default: returns empty list (no pagination).
        """
        return []

    # ── template method ───────────────────────────────────────────────────────

    async def scrape_pipeline(self, url: str, browser: Browser) -> dict:
        """Fixed algorithm. Do not override — override hooks instead."""

        # Feature #1 — Skip already-done URLs
        if self._checkpoint and self._checkpoint.is_done(url):
            log.info("↷ Skipping (checkpoint): %s", url)
            self._bus.publish(
                "url.skip", message=f"Skipped (checkpoint): {url}")
            return {"url": url, "status": "skipped", "error": None}

        result: dict = {
            "url":         url,
            "status":      "pending",
            "http_status": None,
            "size_bytes":  0,
            "elapsed_s":   0.0,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "html_file":   None,
            "meta_file":   None,
            "extra_pages": [],
            "error":       None,
        }

        proxy = await self._proxy_mgr.next_proxy()
        ua = random.choice(self._cfg.user_agents)
        ctx: Optional[BrowserContext] = None
        t_start = time.monotonic()

        async def _do_scrape():
            nonlocal ctx
            ctx = await self._ctx_factory.create(browser, ua, proxy)
            page: Page = await ctx.new_page()
            page.set_default_timeout(self._cfg.page_timeout_ms)

            # Feature #7 — domain rate limit before navigation
            await self._rate_lim.acquire(url)

            self._bus.publish("url.start", message=f"Visiting {url}")
            await self.before_navigate(page, url)

            response = await page.goto(url, wait_until="domcontentloaded")
            result["http_status"] = response.status if response else None

            await self.after_navigate(page, url)
            await HumanBehaviour.mouse_wander(page)
            await HumanBehaviour.gradual_scroll(page, self._cfg)
            await HumanBehaviour.random_delay(self._cfg)

            html = await page.content()
            result["size_bytes"] = len(html.encode())

            # Feature #4 — collect extra pages from pagination hook
            extra = await self.collect_pages(page, url)
            result["extra_pages"] = extra

            await self.after_extract(page, html, url)

            # Feature #3 — skip save if content unchanged
            if self._change_det and not self._change_det.has_changed(url, html):
                result["status"] = "unchanged"
                return html

            fname = self._repo.filename_for(url)
            if self._cfg.save_html:
                result["html_file"] = self._repo.save_html(fname, html)

            parsed = self._parser.parse(html, url)
            meta = {
                "url":         url,
                "timestamp":   result["timestamp"],
                "http_status": result["http_status"],
                "size_bytes":  result["size_bytes"],
                "user_agent":  ua,
                "proxy":       proxy["server"] if proxy else None,
                **parsed,
            }
            result["meta_file"] = self._repo.save_meta(fname, meta)
            result["status"] = "success"
            return html

        try:
            # Feature #2 — wrap in retry policy if configured
            if self._retry:
                await self._retry.execute(_do_scrape, label=url)
            else:
                await _do_scrape()

            result["elapsed_s"] = round(time.monotonic() - t_start, 2)

            # Feature #1 — mark checkpoint on success
            if self._checkpoint and result["status"] == "success":
                self._checkpoint.mark_done(url)

            self._bus.publish(
                "url.success",
                url=url,
                elapsed_s=result["elapsed_s"],
                message=(
                    f"Done {url} "
                    f"({result['size_bytes']} bytes, "
                    f"HTTP {result['http_status']}, "
                    f"{result['elapsed_s']}s)"
                ),
            )

        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            result["elapsed_s"] = round(time.monotonic() - t_start, 2)
            self._bus.publish("url.error", message=f"Failed {url} — {exc}")

        finally:
            if ctx:
                await ctx.close()

        return result
