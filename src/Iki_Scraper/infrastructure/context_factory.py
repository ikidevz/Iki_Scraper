
from ..config import ScraperConfig
from playwright.async_api import Browser, BrowserContext

from typing import Optional


class BrowserContextFactory:
    """Builds a fully-configured BrowserContext. Hides all Playwright kwargs."""

    _WEBDRIVER_MASK = (
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    def __init__(self, cfg: ScraperConfig):
        self._cfg = cfg

    async def create(
        self,
        browser: Browser,
        user_agent: str,
        proxy: Optional[dict],
    ) -> BrowserContext:
        kwargs: dict = {
            "user_agent":  user_agent,
            "viewport":    self._cfg.viewport,
            "locale":      "en-US",
            "timezone_id": "America/New_York",
        }
        if proxy:
            kwargs["proxy"] = proxy

        ctx = await browser.new_context(**kwargs)
        await ctx.add_init_script(self._WEBDRIVER_MASK)
        return ctx
