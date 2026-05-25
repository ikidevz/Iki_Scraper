"""Stateless helpers for human-simulation."""
import asyncio
import random

from ..config import ScraperConfig
from playwright.async_api import Page


class HumanBehaviour:
    @staticmethod
    async def random_delay(cfg: ScraperConfig) -> None:
        await asyncio.sleep(random.uniform(cfg.min_delay, cfg.max_delay))

    @staticmethod
    async def mouse_wander(page: Page) -> None:
        vw = page.viewport_size or {"width": 1366, "height": 768}
        for _ in range(random.randint(4, 8)):
            x = random.randint(50, vw["width"] - 50)
            y = random.randint(50, vw["height"] - 50)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    @staticmethod
    async def gradual_scroll(page: Page, cfg: ScraperConfig) -> None:
        height: int = await page.evaluate("document.body.scrollHeight")
        pos = 0
        while pos < height:
            pos = min(pos + cfg.scroll_step_px, height)
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await asyncio.sleep(cfg.scroll_interval_sec)
            new_h: int = await page.evaluate("document.body.scrollHeight")
            if new_h > height:
                height = new_h
