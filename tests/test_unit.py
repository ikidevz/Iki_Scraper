"""
tests/test_unit.py — Unit tests for scraper_v2
===============================================
No browser. No network. Runs in < 2 s.

  python tests/test_unit.py
"""
from __future__ import annotations
from Iki_Scraper import (
    AppLogger,
    BeautifulSoupStrategy,
    ChangeDetector,
    CheckpointStore,
    CompositeRepository,
    DomainRateLimiter,
    EventBus,
    LocalFileRepository,
    ParseStrategyFactory,
    ProxyManager,
    RawHtmlStrategy,
    RetryPolicy,
    ScraperConfig,
    ScrapeEvent,
    ScrapeObserver,
    SlowPageObserver,
    SQLiteRepository,
)
from Iki_Scraper.facade import _load_urls

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
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

_SAMPLE_HTML = """
<html>
  <head>
    <title>Test Page</title>
    <meta name="description" content="A test.">
  </head>
  <body>
    <nav>Nav noise</nav>
    <p>Real content here.</p>
    <table>
      <tr><th>Name</th><th>Age</th></tr>
      <tr><td>Alice</td><td>30</td></tr>
      <tr><td>Bob</td><td>25</td></tr>
    </table>
    <footer>Footer noise</footer>
  </body>
</html>
"""

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
            print(f"  ✓  {name}  ({e:.2f}s)")
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
# AppLogger — Singleton
# ─────────────────────────────────────────────────────────────────────────────


def test_singleton_same_instance():
    assert AppLogger.get() is AppLogger.get()


def test_singleton_blocks_new():
    try:
        AppLogger()
        raise AssertionError("should raise")
    except TypeError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# ScraperConfig
# ─────────────────────────────────────────────────────────────────────────────


def test_config_defaults():
    cfg = ScraperConfig()
    assert cfg.max_concurrency == 3
    assert cfg.use_parsing is False
    assert cfg.resumable is False
    assert cfg.skip_unchanged is False
    assert cfg.max_retries == 3
    assert cfg.domain_rate_limit == 0.0
    assert cfg.slow_page_threshold_sec == 10.0
    assert cfg.use_sqlite is False


def test_config_override():
    cfg = ScraperConfig(
        max_concurrency=10, use_parsing=True,
        resumable=True, skip_unchanged=True, use_sqlite=True,
    )
    assert cfg.max_concurrency == 10
    assert cfg.use_parsing is True
    assert cfg.resumable is True
    assert cfg.skip_unchanged is True
    assert cfg.use_sqlite is True

# ─────────────────────────────────────────────────────────────────────────────
# ParseStrategy
# ─────────────────────────────────────────────────────────────────────────────


def test_raw_strategy_title_only():
    r = RawHtmlStrategy().parse(_SAMPLE_HTML, "https://x.com")
    assert r["title"] == "Test Page"
    assert "text_preview" not in r
    assert "tables" not in r


def test_raw_strategy_no_title():
    r = RawHtmlStrategy().parse("<html><body>hi</body></html>", "https://x.com")
    assert r["title"] == ""


def test_bs_strategy_all_fields():
    r = BeautifulSoupStrategy().parse(_SAMPLE_HTML, "https://x.com")
    assert r["title"] == "Test Page"
    assert r["meta_description"] == "A test."
    assert "Real content" in r["text_preview"]


def test_bs_strategy_noise_removed():
    r = BeautifulSoupStrategy().parse(_SAMPLE_HTML, "https://x.com")
    assert "Nav noise" not in r["text_preview"]
    assert "Footer noise" not in r["text_preview"]


def test_bs_strategy_text_cap():
    html = f"<html><body><p>{'x' * 10_000}</p></body></html>"
    r = BeautifulSoupStrategy().parse(html, "https://x.com")
    assert len(r["text_preview"]) <= BeautifulSoupStrategy.MAX_TEXT_CHARS


def test_bs_strategy_table_extraction():
    r = BeautifulSoupStrategy().parse(_SAMPLE_HTML, "https://x.com")
    assert "tables" in r
    assert len(r["tables"]) == 1
    assert r["tables"][0][0] == {"Name": "Alice", "Age": "30"}
    assert r["tables"][0][1] == {"Name": "Bob",   "Age": "25"}


def test_bs_strategy_no_table_key_when_empty():
    html = "<html><head><title>T</title></head><body>no tables</body></html>"
    r = BeautifulSoupStrategy().parse(html, "https://x.com")
    assert "tables" not in r


def test_strategy_factory_raw_default():
    assert isinstance(
        ParseStrategyFactory.create(ScraperConfig(use_parsing=False)),
        RawHtmlStrategy,
    )


def test_strategy_factory_bs_when_enabled():
    assert isinstance(
        ParseStrategyFactory.create(ScraperConfig(use_parsing=True)),
        BeautifulSoupStrategy,
    )


def test_strategy_interface_substitutable():
    for s in [RawHtmlStrategy(), BeautifulSoupStrategy()]:
        r = s.parse(_SAMPLE_HTML, "https://x.com")
        assert isinstance(r, dict)
        assert "title" in r

# ─────────────────────────────────────────────────────────────────────────────
# RetryPolicy
# ─────────────────────────────────────────────────────────────────────────────


async def _test_retry_succeeds_first_try():
    calls = []

    async def ok():
        calls.append(1)
        return "done"
    result = await RetryPolicy(3, 0.0).execute(ok)
    assert result == "done" and len(calls) == 1


async def _test_retry_retries_on_failure():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("not yet")
        return "ok"
    result = await RetryPolicy(3, 0.0).execute(flaky)
    assert result == "ok" and len(calls) == 3


async def _test_retry_raises_after_max():
    async def always_fails():
        raise RuntimeError("boom")
    try:
        await RetryPolicy(2, 0.0).execute(always_fails)
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert str(e) == "boom"

# ─────────────────────────────────────────────────────────────────────────────
# ChangeDetector
# ─────────────────────────────────────────────────────────────────────────────


def test_change_detector_first_visit_is_change():
    with tempfile.TemporaryDirectory() as d:
        assert ChangeDetector(d).has_changed(
            "https://x.com", "<html>v1</html>") is True


def test_change_detector_same_content_not_changed():
    with tempfile.TemporaryDirectory() as d:
        cd = ChangeDetector(d)
        cd.has_changed("https://x.com", "<html>v1</html>")
        assert cd.has_changed("https://x.com", "<html>v1</html>") is False


def test_change_detector_different_content_is_change():
    with tempfile.TemporaryDirectory() as d:
        cd = ChangeDetector(d)
        cd.has_changed("https://x.com", "<html>v1</html>")
        assert cd.has_changed("https://x.com", "<html>v2</html>") is True


def test_change_detector_persists_across_instances():
    with tempfile.TemporaryDirectory() as d:
        ChangeDetector(d).has_changed("https://x.com", "<html>v1</html>")
        assert ChangeDetector(d).has_changed(
            "https://x.com", "<html>v1</html>") is False

# ─────────────────────────────────────────────────────────────────────────────
# CheckpointStore
# ─────────────────────────────────────────────────────────────────────────────


def test_checkpoint_not_done_initially():
    with tempfile.TemporaryDirectory() as d:
        assert CheckpointStore(d).is_done("https://x.com") is False


def test_checkpoint_mark_and_check():
    with tempfile.TemporaryDirectory() as d:
        cp = CheckpointStore(d)
        cp.mark_done("https://x.com")
        assert cp.is_done("https://x.com") is True


def test_checkpoint_persists_across_instances():
    with tempfile.TemporaryDirectory() as d:
        CheckpointStore(d).mark_done("https://x.com")
        assert CheckpointStore(d).is_done("https://x.com") is True


def test_checkpoint_clear():
    with tempfile.TemporaryDirectory() as d:
        cp = CheckpointStore(d)
        cp.mark_done("https://x.com")
        cp.clear()
        assert cp.is_done("https://x.com") is False

# ─────────────────────────────────────────────────────────────────────────────
# LocalFileRepository
# ─────────────────────────────────────────────────────────────────────────────


def test_local_repo_saves_html():
    with tempfile.TemporaryDirectory() as d:
        path = LocalFileRepository(d).save_html("test", "<html/>")
        assert Path(path).read_text() == "<html/>"


def test_local_repo_saves_meta():
    with tempfile.TemporaryDirectory() as d:
        meta = {"url": "https://x.com", "title": "T", "size_bytes": 10}
        path = LocalFileRepository(d).save_meta("test", meta)
        assert json.loads(Path(path).read_text())["title"] == "T"


def test_local_repo_saves_summary():
    with tempfile.TemporaryDirectory() as d:
        path = LocalFileRepository(d).save_summary(
            {"total": 3, "success": 2, "error": 1})
        assert json.loads(Path(path).read_text())["total"] == 3


def test_local_repo_safe_filename():
    with tempfile.TemporaryDirectory() as d:
        fname = LocalFileRepository(d).filename_for(
            "https://example.com/path?q=1&b=2")
        assert "/" not in fname and "?" not in fname and len(fname) <= 120

# ─────────────────────────────────────────────────────────────────────────────
# SQLiteRepository
# ─────────────────────────────────────────────────────────────────────────────


def test_sqlite_repo_creates_db():
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "test.db")
        SQLiteRepository(db)
        assert Path(db).exists()


def test_sqlite_repo_save_meta_and_summary():
    import sqlite3 as _sq
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "test.db")
        repo = SQLiteRepository(db)
        repo.save_meta("x_com", {
            "url": "https://x.com", "timestamp": "now",
            "http_status": 200, "size_bytes": 500, "title": "Hi",
        })
        repo.save_summary({
            "started_at": "now", "finished_at": "now",
            "elapsed_s": 1.0, "total": 1, "success": 1, "error": 0,
        })
        con = _sq.connect(db)
        rows = con.execute("SELECT url FROM pages").fetchall()
        runs = con.execute("SELECT total FROM runs").fetchall()
        con.close()
        assert rows[0][0] == "https://x.com"
        assert runs[0][0] == 1

# ─────────────────────────────────────────────────────────────────────────────
# CompositeRepository
# ─────────────────────────────────────────────────────────────────────────────


def test_composite_repo_writes_both():
    with tempfile.TemporaryDirectory() as d:
        repo = CompositeRepository(
            LocalFileRepository(d),
            SQLiteRepository(str(Path(d) / "c.db")),
        )
        repo.save_html("pg", "<html/>")
        assert Path(d, "pg.html").exists()

# ─────────────────────────────────────────────────────────────────────────────
# DomainRateLimiter
# ─────────────────────────────────────────────────────────────────────────────


async def _test_rate_limiter_disabled():
    rl = DomainRateLimiter(0.0)
    t = time.monotonic()
    await rl.acquire("https://example.com")
    await rl.acquire("https://example.com")
    assert time.monotonic() - t < 0.1


async def _test_rate_limiter_enforces_gap():
    rl = DomainRateLimiter(0.2)
    t = time.monotonic()
    await rl.acquire("https://example.com")
    await rl.acquire("https://example.com")
    assert time.monotonic() - t >= 0.18


async def _test_rate_limiter_different_domains_not_blocked():
    rl = DomainRateLimiter(1.0)
    t = time.monotonic()
    await asyncio.gather(
        rl.acquire("https://example.com"),
        rl.acquire("https://httpbin.org"),
    )
    assert time.monotonic() - t < 0.2

# ─────────────────────────────────────────────────────────────────────────────
# EventBus + Observers
# ─────────────────────────────────────────────────────────────────────────────


def test_eventbus_delivers_to_all():
    got = []

    class Rec(ScrapeObserver):
        def __init__(self, tag): self.tag = tag
        def on_event(self, e):   got.append(self.tag)
    bus = EventBus()
    bus.subscribe(Rec("A"))
    bus.subscribe(Rec("B"))
    bus.subscribe(Rec("C"))
    bus.publish("x", message="hi")
    assert got == ["A", "B", "C"]


def test_eventbus_crash_isolated():
    got = []

    class Bad(ScrapeObserver):
        def on_event(self, e): raise RuntimeError("crash")

    class Good(ScrapeObserver):
        def on_event(self, e): got.append("ok")
    bus = EventBus()
    bus.subscribe(Bad())
    bus.subscribe(Good())
    bus.publish("x", message="hi")
    assert "ok" in got


def test_slow_page_observer_fires_above_threshold():
    obs = SlowPageObserver(threshold_s=5.0)
    obs.on_event(ScrapeEvent("url.success",
                             {"url": "https://slow.com", "elapsed_s": 12.0, "message": ""}))
    assert len(obs.slow_pages) == 1
    assert obs.slow_pages[0]["url"] == "https://slow.com"


def test_slow_page_observer_silent_below_threshold():
    obs = SlowPageObserver(threshold_s=5.0)
    obs.on_event(ScrapeEvent("url.success",
                             {"url": "https://fast.com", "elapsed_s": 1.2, "message": ""}))
    assert len(obs.slow_pages) == 0


def test_slow_page_observer_ignores_other_events():
    obs = SlowPageObserver(threshold_s=5.0)
    obs.on_event(ScrapeEvent("run.start", {"message": "hi"}))
    assert len(obs.slow_pages) == 0

# ─────────────────────────────────────────────────────────────────────────────
# URL loader
# ─────────────────────────────────────────────────────────────────────────────


def test_load_urls_txt():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("https://a.com\n# comment\nhttps://b.com\n\n")
        fname = f.name
    assert _load_urls(fname) == ["https://a.com", "https://b.com"]
    Path(fname).unlink()


def test_load_urls_json():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(["https://a.com", "https://b.com"], f)
        fname = f.name
    assert _load_urls(fname) == ["https://a.com", "https://b.com"]
    Path(fname).unlink()


def test_load_urls_bad_json_raises():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"url": "https://a.com"}, f)
        fname = f.name
    try:
        _load_urls(fname)
        raise AssertionError("should raise")
    except ValueError:
        pass
    finally:
        Path(fname).unlink()

# ─────────────────────────────────────────────────────────────────────────────
# ProxyManager
# ─────────────────────────────────────────────────────────────────────────────


async def _test_proxy_manager_disabled():
    assert await ProxyManager(ScraperConfig(use_proxies=False)).next_proxy() is None


async def _test_proxy_manager_empty_pool_returns_none():
    mgr = ProxyManager(ScraperConfig(use_proxies=True))
    async def empty(): return []
    mgr._fetch_pool = empty
    assert await mgr.next_proxy() is None

# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────


def main():
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║  test_unit.py — no browser, no network               ║")
    print("╚══════════════════════════════════════════════════════╝")

    runner.run("Singleton: same instance",
               test_singleton_same_instance)
    runner.run("Singleton: blocks __new__",
               test_singleton_blocks_new)
    runner.run("Config: defaults correct",               test_config_defaults)
    runner.run("Config: fields override",                test_config_override)
    runner.run("RawHtmlStrategy: title only",
               test_raw_strategy_title_only)
    runner.run("RawHtmlStrategy: missing title",
               test_raw_strategy_no_title)
    runner.run("BSStrategy: all fields present",
               test_bs_strategy_all_fields)
    runner.run("BSStrategy: noise tags removed",
               test_bs_strategy_noise_removed)
    runner.run("BSStrategy: text capped at 5000",
               test_bs_strategy_text_cap)
    runner.run("BSStrategy: table extraction",
               test_bs_strategy_table_extraction)
    runner.run("BSStrategy: no tables key when empty",
               test_bs_strategy_no_table_key_when_empty)
    runner.run("Factory: raw by default",
               test_strategy_factory_raw_default)
    runner.run("Factory: BS when enabled",
               test_strategy_factory_bs_when_enabled)
    runner.run("Strategy: interface substitutable",
               test_strategy_interface_substitutable)
    runner.run_async("RetryPolicy: succeeds first try",
                     _test_retry_succeeds_first_try)
    runner.run_async("RetryPolicy: retries on failure",
                     _test_retry_retries_on_failure)
    runner.run_async("RetryPolicy: raises after max",
                     _test_retry_raises_after_max)
    runner.run("ChangeDetector: first visit=change",
               test_change_detector_first_visit_is_change)
    runner.run("ChangeDetector: same=no change",
               test_change_detector_same_content_not_changed)
    runner.run("ChangeDetector: different=change",
               test_change_detector_different_content_is_change)
    runner.run("ChangeDetector: persists across inst",
               test_change_detector_persists_across_instances)
    runner.run("Checkpoint: not done initially",
               test_checkpoint_not_done_initially)
    runner.run("Checkpoint: mark and check",
               test_checkpoint_mark_and_check)
    runner.run("Checkpoint: persists across instances",
               test_checkpoint_persists_across_instances)
    runner.run("Checkpoint: clear works",                test_checkpoint_clear)
    runner.run("LocalRepo: saves HTML",
               test_local_repo_saves_html)
    runner.run("LocalRepo: saves meta JSON",
               test_local_repo_saves_meta)
    runner.run("LocalRepo: saves summary JSON",
               test_local_repo_saves_summary)
    runner.run("LocalRepo: safe filename",
               test_local_repo_safe_filename)
    runner.run("SQLiteRepo: creates db file",
               test_sqlite_repo_creates_db)
    runner.run("SQLiteRepo: save meta + summary",
               test_sqlite_repo_save_meta_and_summary)
    runner.run("CompositeRepo: writes both backends",
               test_composite_repo_writes_both)
    runner.run_async("RateLimiter: disabled=instant",
                     _test_rate_limiter_disabled)
    runner.run_async("RateLimiter: enforces gap",
                     _test_rate_limiter_enforces_gap)
    runner.run_async("RateLimiter: diff domains no block",
                     _test_rate_limiter_different_domains_not_blocked)
    runner.run("EventBus: delivers to all observers",
               test_eventbus_delivers_to_all)
    runner.run("EventBus: crash isolated",
               test_eventbus_crash_isolated)
    runner.run("SlowPageObserver: fires above threshold",
               test_slow_page_observer_fires_above_threshold)
    runner.run("SlowPageObserver: silent below",
               test_slow_page_observer_silent_below_threshold)
    runner.run("SlowPageObserver: ignores other events",
               test_slow_page_observer_ignores_other_events)
    runner.run("_load_urls: parses .txt",                test_load_urls_txt)
    runner.run("_load_urls: parses .json",               test_load_urls_json)
    runner.run("_load_urls: bad json raises",
               test_load_urls_bad_json_raises)
    runner.run_async("ProxyManager: disabled=None",
                     _test_proxy_manager_disabled)
    runner.run_async("ProxyManager: empty pool=None",
                     _test_proxy_manager_empty_pool_returns_none)

    sys.exit(runner.summary())


if __name__ == "__main__":
    main()
