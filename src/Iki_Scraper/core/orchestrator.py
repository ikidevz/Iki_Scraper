"""
Drives URLs through BaseScraper with asyncio.Semaphore concurrency.
Follows up on extra_pages discovered via the pagination hook (Feature #4).
Aggregates results and emits run-level events.
"""
from datetime import datetime, timezone
from playwright.async_api import async_playwright

from ..config import ScraperConfig
from ..patterns.base_scraper import BaseScraper
from ..patterns.repository import OutputRepository
from ..patterns.observer import EventBus

import asyncio


class ScraperOrchestrator:

    def __init__(
        self,
        cfg:      ScraperConfig,
        scraper:  BaseScraper,
        repo:     OutputRepository,
        bus:      EventBus,
    ):
        self._cfg = cfg
        self._scraper = scraper
        self._repo = repo
        self._bus = bus

    async def run(self, urls: list[str]) -> dict:
        seen: set[str] = set(urls)
        queue: list[str] = list(urls)

        summary: dict = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total":      len(queue),
            "success":    0,
            "error":      0,
            "skipped":    0,
            "unchanged":  0,
            "results":    [],
        }

        self._bus.publish(
            "run.start", message=f"Starting run — {len(queue)} URL(s)")
        sem = asyncio.Semaphore(self._cfg.max_concurrency)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self._cfg.headless)

            async def bounded(url: str) -> dict:
                async with sem:
                    return await self._scraper.scrape_pipeline(url, browser)

            while queue:
                results = await asyncio.gather(*[bounded(u) for u in queue])
                queue = []

                for r in results:
                    summary["results"].append(r)
                    status = r.get("status", "error")
                    if status == "success":
                        summary["success"] += 1
                    elif status == "error":
                        summary["error"] += 1
                    elif status == "skipped":
                        summary["skipped"] += 1
                    elif status == "unchanged":
                        summary["unchanged"] += 1

                    # Feature #4 — enqueue newly discovered pages
                    for extra_url in r.get("extra_pages", []):
                        if extra_url not in seen:
                            seen.add(extra_url)
                            queue.append(extra_url)
                            summary["total"] += 1

            await browser.close()

        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["elapsed_s"] = round(
            (
                datetime.fromisoformat(summary["finished_at"])
                - datetime.fromisoformat(summary["started_at"])
            ).total_seconds(),
            2,
        )

        self._repo.save_summary(summary)
        self._bus.publish(
            "run.done",
            message=(
                f"Run complete — "
                f"✓ {summary['success']}  "
                f"✗ {summary['error']}  "
                f"↷ {summary['skipped']}  "
                f"({summary['elapsed_s']}s)"
            ),
        )
        return summary
