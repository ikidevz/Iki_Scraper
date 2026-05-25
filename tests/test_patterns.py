"""
tests/test_integration.py — Integration tests for scraper_v2
=============================================================
Requires: playwright install chromium
Runs in ~40 s.

  python tests/test_integration.py
"""
from __future__ import annotations
from Iki_Scraper import (
    ScraperConfig,
    ScraperFacade,
    ScrapeObserver,
    ScrapeEvent,
)

import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import nest_asyncio
nest_asyncio.apply()

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Shared URLs
# ─────────────────────────────────────────────────────────────────────────────

_URLS = ["https://example.com", "https://httpbin.org/html"]

# ─────────────────────────────────────────────────────────────────────────────
# Minimal runner
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Result:
    name: str
    passed: bool
    message: str = ""
    elapsed: float = 0.0


class TestRunner:
    def __init__(self):
        self._results: list[Result] = []

    def run(self, name: str, fn):
        t = time.perf_counter()
        try:
            fn()
            e = time.perf_counter() - t
            self._results.append(Result(name, True, elapsed=e))
            print(f"  ✓  {name}  ({e:.1f}s)")
        except Exception as exc:
            e = time.perf_counter() - t
            self._results.append(Result(name, False, str(exc), e))
            print(f"  ✗  {name}\n       {exc}")

    def run_async(self, name: str, coro_fn):
        self.run(name, lambda: asyncio.run(coro_fn()))

    def summary(self) -> int:
        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)
        print(f"\n{'─'*55}")
        print(f"  {passed}/{total} passed   {total - passed} failed")
        print(f"{'─'*55}")
        return total - passed


runner = TestRunner()

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fast_cfg(tmpdir: str, **extra) -> ScraperConfig:
    """Base config that keeps tests quick without sacrificing correctness."""
    defaults = dict(
        output_dir=tmpdir,
        save_html=True,
        use_parsing=True,

        min_delay=0.2,
        max_delay=0.4,
        scroll_interval_sec=0.1,

        max_retries=0,
    )

    defaults.update(extra)
    return ScraperConfig(**defaults)

# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


async def _scrape_one_raw():
    with tempfile.TemporaryDirectory() as d:
        s = ScraperFacade(_fast_cfg(d, max_concurrency=1)
                          ).scrape_one("https://example.com")
        assert s["success"] == 1 and s["error"] == 0
        r = s["results"][0]
        assert r["status"] == "success"
        assert r["http_status"] == 200
        assert r["size_bytes"] > 100
        assert Path(r["html_file"]).exists()
        meta = json.loads(Path(r["meta_file"]).read_text())
        for k in ("url", "timestamp", "http_status", "size_bytes", "title"):
            assert k in meta, f"meta missing key: {k}"


async def _scrape_one_with_parsing():
    with tempfile.TemporaryDirectory() as d:
        s = ScraperFacade(_fast_cfg(d, use_parsing=True)
                          ).scrape_one("https://example.com")
        meta = json.loads(Path(s["results"][0]["meta_file"]).read_text())
        assert "meta_description" in meta
        assert "text_preview" in meta


async def _scrape_many_concurrency():
    with tempfile.TemporaryDirectory() as d:
        s = ScraperFacade(_fast_cfg(d, max_concurrency=2)).scrape_many(_URLS)
        assert s["total"] == len(_URLS)
        assert (Path(d) / "scrape_summary.json").exists()


async def _resumable_skips_done():
    with tempfile.TemporaryDirectory() as d:
        cfg = _fast_cfg(d, resumable=True)
        # first run — scrapes
        s1 = ScraperFacade(cfg).scrape_one("https://example.com")
        assert s1["success"] == 1
        # second run — must skip
        s2 = ScraperFacade(cfg).scrape_one("https://example.com")
        assert s2["results"][0]["status"] == "skipped"


async def _change_detection_skip_unchanged():
    with tempfile.TemporaryDirectory() as d:
        cfg = _fast_cfg(d, skip_unchanged=True)
        ScraperFacade(cfg).scrape_one("https://example.com")
        s2 = ScraperFacade(cfg).scrape_one("https://example.com")
        assert s2["results"][0]["status"] in ("unchanged", "success")


async def _sqlite_backend():
    import sqlite3 as _sq
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "test.db")
        ScraperFacade(_fast_cfg(d, use_sqlite=True, sqlite_path=db)
                      ).scrape_one("https://example.com")
        con = _sq.connect(db)
        rows = con.execute("SELECT url FROM pages").fetchall()
        con.close()
        assert len(rows) >= 1


async def _slow_page_observer_fires():
    with tempfile.TemporaryDirectory() as d:
        cfg = _fast_cfg(d, slow_page_threshold_sec=0.001)
        f = ScraperFacade(cfg)
        f.scrape_one("https://example.com")
        assert len(f.slow_pages) >= 1


async def _retry_graceful_on_bad_url():
    with tempfile.TemporaryDirectory() as d:
        cfg = _fast_cfg(d, max_retries=1, retry_base_delay_sec=0.1,
                        page_timeout_ms=5_000)
        s = ScraperFacade(cfg).scrape_one(
            "https://this-does-not-exist-xyz.invalid")
        assert s["results"][0]["status"] == "error"
        assert s["error"] == 1


async def _domain_rate_limit_adds_delay():
    with tempfile.TemporaryDirectory() as d:
        cfg = _fast_cfg(d, domain_rate_limit=0.5, max_concurrency=2)
        t = time.monotonic()
        ScraperFacade(cfg).scrape_many(
            ["https://example.com", "https://example.com/"])
        assert time.monotonic() - t >= 0.4


async def _observer_receives_events():
    received: list[str] = []

    class Rec(ScrapeObserver):
        def on_event(self, e: ScrapeEvent): received.append(e.name)
    with tempfile.TemporaryDirectory() as d:
        f = ScraperFacade(_fast_cfg(d))
        f.add_observer(Rec())
        f.scrape_one("https://example.com")
    assert "run.start" in received
    assert "url.start" in received
    assert "run.done" in received


async def _summary_json_structure():
    with tempfile.TemporaryDirectory() as d:
        ScraperFacade(_fast_cfg(d)).scrape_one("https://example.com")
        s = json.loads((Path(d) / "scrape_summary.json").read_text())
        for k in ("started_at", "finished_at", "elapsed_s", "total",
                  "success", "error", "skipped", "unchanged", "results"):
            assert k in s, f"summary missing key: {k}"


async def _scrape_file_txt():
    with tempfile.TemporaryDirectory() as d:
        url_file = Path(d) / "urls.txt"
        url_file.write_text("https://example.com\nhttps://httpbin.org/html\n")
        s = ScraperFacade(_fast_cfg(str(Path(d) / "out"))
                          ).scrape_file(str(url_file))
        assert s["total"] == 2


async def _scrape_file_json():
    with tempfile.TemporaryDirectory() as d:
        url_file = Path(d) / "urls.json"
        url_file.write_text(json.dumps(["https://example.com"]))
        s = ScraperFacade(_fast_cfg(str(Path(d) / "out"))
                          ).scrape_file(str(url_file))
        assert s["total"] == 1 and s["success"] == 1

# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────


def main():
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║  test_integration.py — real Chromium + public URLs   ║")
    print("╚══════════════════════════════════════════════════════╝")
    print("  Requires: playwright install chromium\n")

    runner.run_async("Scrape one URL — raw mode",          _scrape_one_raw)
    runner.run_async("Scrape one URL — BS parsing",
                     _scrape_one_with_parsing)
    runner.run_async("Scrape many — concurrency 2",
                     _scrape_many_concurrency)
    runner.run_async("Resumable: second run skips done",
                     _resumable_skips_done)
    runner.run_async("ChangeDetect: skip unchanged",
                     _change_detection_skip_unchanged)
    runner.run_async("SQLite backend writes to db",        _sqlite_backend)
    runner.run_async("SlowPageObserver fires",
                     _slow_page_observer_fires)
    runner.run_async("Retry: bad URL handled gracefully",
                     _retry_graceful_on_bad_url)
    runner.run_async("DomainRateLimit: adds delay",
                     _domain_rate_limit_adds_delay)
    runner.run_async("Observer: receives all events",
                     _observer_receives_events)
    runner.run_async("Summary JSON: all keys present",
                     _summary_json_structure)
    runner.run_async("scrape_file(): .txt input",          _scrape_file_txt)
    runner.run_async("scrape_file(): .json input",         _scrape_file_json)

    sys.exit(runner.summary())


if __name__ == "__main__":
    main()
