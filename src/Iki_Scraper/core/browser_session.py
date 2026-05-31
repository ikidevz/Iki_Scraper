"""
browser_session.py — Lightweight single-page browser session
=============================================================
Encapsulates the open/navigate/close lifecycle for one-shot browser
queries (select, select_all, select_many, select_table).


Usage
-----
    async with BrowserSession(cfg) as page:
        text = await page.inner_text("h1")
"""

from __future__ import annotations

import random
from typing import Optional, TYPE_CHECKING

from playwright.async_api import async_playwright, Page, Browser

from ..config import ScraperConfig
from ..infrastructure.context_factory import BrowserContextFactory

if TYPE_CHECKING:
    from playwright.async_api import Playwright


class BrowserSession:
    """
    Async context manager that opens Chromium, navigates to a URL,
    and yields the live Playwright ``Page``.

    On exit (normal or exception) the browser and Playwright instance
    are always closed.

    Example::

        session = BrowserSession(cfg)
        async with session.open(url) as page:
            text = await page.inner_text("h1")
    """

    def __init__(self, cfg: ScraperConfig) -> None:
        self._cfg = cfg
        self._ctx_factory = BrowserContextFactory(cfg)

        # Set during __aenter__
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._url: str = ""

    def open(self, url: str) -> "BrowserSession":
        """Set the target URL and return self for use in ``async with``."""
        self._url = url
        return self

    async def __aenter__(self) -> Page:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._cfg.headless
        )
        ua = random.choice(self._cfg.user_agents)
        ctx = await self._ctx_factory.create(self._browser, ua, proxy=None)
        page: Page = await ctx.new_page()
        page.set_default_timeout(self._cfg.page_timeout_ms)
        await page.goto(self._url, wait_until="domcontentloaded")
        return page

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        return False  # do not suppress exceptions
