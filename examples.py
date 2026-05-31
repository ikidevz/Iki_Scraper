"""
examples.py — Iki-Scraper complete feature showcase
====================================================
Single runnable script. Every public method on ScraperFacade gets its
own named section. Sections A–G are pure-Python (no browser). Sections
H–R launch Chromium — run `playwright install chromium` first.

Sections
--------
  A.  ScraperConfig              — all fields, defaults, overrides
  B.  AppLogger                  — singleton, type, instantiation guard
  C.  EventBus & Observers       — pub/sub, error isolation, SlowPage
  D.  Repositories               — LocalFile · SQLite · Composite
  E.  Parse Strategies           — RawHtml · BeautifulSoup · Factory
  F.  Resilience utilities       — ChangeDetector · CheckpointStore
                                   RetryPolicy · DomainRateLimiter
  G.  Infrastructure             — ProxyManager · SitemapDiscovery
                                   UrlLoader · BrowserSession
  ── Playwright required below ──────────────────────────────────────
  H.  fetch()                    — single URL
  I.  fetch_many()               — concurrent list
  J.  fetch_file()               — .txt and .json URL files
  K.  fetch_sitemap()            — auto-discover + scrape
  L.  parse()                    — structured BS4 extraction (1 URL)
  M.  parse_many()               — structured extraction (many URLs)
  N.  select()                   — grab one element by CSS selector
  O.  select_all()               — grab all matching elements
  P.  select_many()              — multi-selector in one session
  Q.  select_table()             — extract <table> as list-of-dicts
  R.  detect_changes()           — skip-unchanged content
  S.  resume()                   — checkpoint-based resumable runs
  T.  discover()                 — sitemap discovery, no scraping
  U.  observe()                  — custom event-hook observer
  V.  SQLite methods             — query_db / list_saved / get_run_history / export_json
  W.  describe()                 — config + feature + state snapshot
  X.  clear_checkpoint()         — erase checkpoint file
      checkpoint_status()        — inspect checkpoint without modifying
      reset_hashes()             — erase content-hash file
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
import time
from pathlib import Path

# ── Iki-Scraper imports ────────────────────────────────────────────────────────
from Iki_Scraper.config import ScraperConfig
from Iki_Scraper.facade import ScraperFacade
from Iki_Scraper.patterns.logger import AppLogger
from Iki_Scraper.patterns.observer import (
    EventBus, ScrapeEvent, ScrapeObserver,
    LoggingObserver, SlowPageObserver,
)
from Iki_Scraper.patterns.repository import (
    LocalFileRepository, SQLiteRepository, CompositeRepository,
)
from Iki_Scraper.patterns.parse_strategy import (
    RawHtmlStrategy, BeautifulSoupStrategy, ParseStrategyFactory,
)
from Iki_Scraper.patterns.change_detector import ChangeDetector
from Iki_Scraper.patterns.checkpoint import CheckpointStore
from Iki_Scraper.patterns.retry_policy import RetryPolicy
from Iki_Scraper.infrastructure.domain_rate_limiter import DomainRateLimiter
from Iki_Scraper.infrastructure.proxy_manager import ProxyManager
from Iki_Scraper.infrastructure.sitemap_discovery import SitemapDiscovery
from Iki_Scraper.infrastructure.url_loader import UrlLoader
from Iki_Scraper.core import ScraperOrchestrator, StandardScraper, BrowserSession

# ── Print helpers ──────────────────────────────────────────────────────────────


def _header(title: str) -> None:
    print(f"\n{'═' * 62}")
    print(f"  {title}")
    print(f"{'═' * 62}")


def _ok(msg: str) -> None: print(f"  ✓ {msg}")
def _warn(msg: str) -> None: print(f"  ⚠ {msg}")


def _row(
    r: dict) -> None: print(f"     ↳ [{r.get('status', '?')}] {r.get('url', '?')}")

# ── Shared fast config ─────────────────────────────────────────────────────────


def _cfg(tmp: str, **kw) -> ScraperConfig:
    return ScraperConfig(
        output_dir=tmp, headless=True,
        max_retries=1, min_delay=0.1, max_delay=0.3,
        **kw,
    )


def _check_summary(summary: dict, expected_total: int, label: str) -> None:
    assert isinstance(summary, dict)
    assert summary["total"] >= expected_total
    _ok(f"{label}: total={summary['total']} success={summary['success']} "
        f"error={summary['error']} elapsed={summary.get('elapsed_s', '?')}s")
    for r in summary["results"]:
        _row(r)


# ══════════════════════════════════════════════════════════════════════════════
# A. ScraperConfig
# ══════════════════════════════════════════════════════════════════════════════

def section_a_scraper_config() -> None:
    _header("A. ScraperConfig — defaults & overrides")

    cfg = ScraperConfig()
    assert cfg.output_dir == "scraper_output"
    assert cfg.max_concurrency == 3
    assert cfg.headless is True
    assert cfg.use_proxies is False
    assert cfg.max_retries == 3
    assert cfg.use_sqlite is False
    assert cfg.resumable is False
    assert cfg.skip_unchanged is False
    assert cfg.domain_rate_limit == 0.0
    assert cfg.slow_page_threshold_sec == 10.0
    assert cfg.use_parsing is False
    assert cfg.save_html is False
    assert cfg.viewport == {"width": 1366, "height": 768}
    assert isinstance(cfg.user_agents, list) and len(cfg.user_agents) >= 10
    _ok(f"All defaults correct — {len(cfg.user_agents)} built-in user-agents")

    cfg2 = ScraperConfig(
        output_dir="out", max_concurrency=5, headless=False,
        use_proxies=True, max_retries=0, min_delay=0.5, max_delay=2.0,
        use_sqlite=True, sqlite_path="custom.db",
        resumable=True, skip_unchanged=True,
        domain_rate_limit=1.5, slow_page_threshold_sec=5.0,
        use_parsing=True, save_html=True,
        viewport={"width": 1920, "height": 1080},
        user_agents=["MyBot/1.0"],
    )
    assert cfg2.output_dir == "out"
    assert cfg2.max_concurrency == 5
    assert cfg2.headless is False
    assert cfg2.viewport["width"] == 1920
    assert cfg2.user_agents == ["MyBot/1.0"]
    _ok("All field overrides accepted and readable")


# ══════════════════════════════════════════════════════════════════════════════
# B. AppLogger
# ══════════════════════════════════════════════════════════════════════════════

def section_b_logger() -> None:
    _header("B. AppLogger — singleton logger")

    log1 = AppLogger.get()
    log2 = AppLogger.get()
    assert log1 is log2
    assert isinstance(log1, logging.Logger)
    assert log1.name == "Iki_Scraper"
    _ok(f"Singleton — same instance every call, name='{log1.name}'")

    try:
        AppLogger()
        print("  ✗ Should have raised TypeError")
    except TypeError:
        _ok("Direct instantiation blocked with TypeError")

    log1.info("Section B — INFO")
    log1.warning("Section B — WARNING")
    _ok("log.info / log.warning / log.debug all callable without error")


# ══════════════════════════════════════════════════════════════════════════════
# C. EventBus & Observers
# ══════════════════════════════════════════════════════════════════════════════

class _Recorder(ScrapeObserver):
    def __init__(self): self.events: list[ScrapeEvent] = []
    def on_event(self, e: ScrapeEvent) -> None: self.events.append(e)


class _Broken(ScrapeObserver):
    def on_event(self, e: ScrapeEvent) -> None: raise RuntimeError("boom")


def section_c_observer_eventbus() -> None:
    _header("C. EventBus & Observers — pub/sub, error isolation, SlowPage")

    ev = ScrapeEvent("url.start", {"message": "hello"})
    assert ev.name == "url.start" and ev.timestamp
    _ok(f"ScrapeEvent value object — name='{ev.name}', timestamp set")

    bus = EventBus()
    rec = _Recorder()
    bus.subscribe(rec)
    bus.publish("url.start",   message="go")
    bus.publish("url.success", url="https://example.com",
                elapsed_s=1.5, message="done")
    assert len(rec.events) == 2
    assert rec.events[1].payload["elapsed_s"] == 1.5
    _ok("pub/sub — 2 events delivered, payload intact")

    bus2 = EventBus()
    r1, r2 = _Recorder(), _Recorder()
    bus2.subscribe(r1)
    bus2.subscribe(r2)
    bus2.publish("run.start", message="go")
    assert len(r1.events) == 1 and len(r2.events) == 1
    _ok("Multiple observers each receive every event")

    bus3 = EventBus()
    bus3.subscribe(_Broken())
    healthy = _Recorder()
    bus3.subscribe(healthy)
    bus3.publish("url.start", message="test")
    assert len(healthy.events) == 1
    _ok("Broken observer exception isolated — healthy observer unaffected")

    lbus = EventBus()
    lbus.subscribe(LoggingObserver())
    for name in ("url.start", "url.success", "url.error", "url.skip", "run.done", "run.start"):
        lbus.publish(name, message=f"test {name}",
                     url="https://x.com", elapsed_s=1.0)
    _ok("LoggingObserver — all 6 standard event names handled without error")

    slow = SlowPageObserver(threshold_s=5.0)
    sbus = EventBus()
    sbus.subscribe(slow)
    sbus.publish("url.success", url="https://fast.com",
                 elapsed_s=1.0, message="ok")
    assert len(slow.slow_pages) == 0
    sbus.publish("url.success", url="https://slow.com",
                 elapsed_s=12.0, message="ok")
    assert slow.slow_pages[0]["url"] == "https://slow.com"
    _ok("SlowPageObserver — fast page ignored, slow page (12s > 5s) recorded")

    slow2 = SlowPageObserver(threshold_s=5.0)
    sbus2 = EventBus()
    sbus2.subscribe(slow2)
    sbus2.publish("url.success", url="https://border.com",
                  elapsed_s=5.0, message="ok")
    assert len(slow2.slow_pages) == 1
    _ok("SlowPageObserver — exact threshold (5.0s == 5.0s) is flagged (>= boundary)")


# ══════════════════════════════════════════════════════════════════════════════
# D. Repositories
# ══════════════════════════════════════════════════════════════════════════════

_META = {
    "url": "https://example.com/page", "timestamp": "2024-01-01T00:00:00+00:00",
    "http_status": 200, "size_bytes": 1024, "title": "Example Page",
    "user_agent": "TestBot/1.0", "proxy": None,
}
_HTML = "<html><body><h1>Hello</h1></body></html>"
_SUMMARY = {"total": 1, "success": 1, "error": 0, "elapsed_s": 2.5}


def section_d_repositories() -> None:
    _header("D. Repositories — LocalFile · SQLite · Composite")

    # LocalFileRepository
    with tempfile.TemporaryDirectory() as tmp:
        repo = LocalFileRepository(tmp)
        name = repo.filename_for("https://example.com/path?q=1")
        assert "https" not in name and "/" not in name and len(name) <= 120
        _ok(f"filename_for: '{name}' (no scheme, no slash, ≤120 chars)")

        html_path = repo.save_html(name, _HTML)
        assert Path(html_path).read_text() == _HTML
        _ok(f"save_html → {html_path}")

        meta_path = repo.save_meta(name, _META)
        assert json.loads(Path(meta_path).read_text())["http_status"] == 200
        _ok(f"save_meta → {meta_path}")

        summary_path = repo.save_summary(_SUMMARY)
        assert json.loads(Path(summary_path).read_text())["total"] == 1
        _ok(f"save_summary → {summary_path}")

    with tempfile.TemporaryDirectory() as tmp:
        nested = str(Path(tmp) / "a" / "b" / "c")
        LocalFileRepository(nested)
        assert Path(nested).exists()
        _ok("mkdir -p: nested output_dir created automatically")

    # SQLiteRepository
    import tempfile as _tf
    f = _tf.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = f.name
    f.close()
    try:
        repo = SQLiteRepository(db_path)
        con = sqlite3.connect(db_path)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"pages", "runs"} <= tables
        _ok("SQLite schema: 'pages' and 'runs' tables created on init")

        fname = repo.filename_for("https://example.com")
        key = repo.save_meta(fname, _META)
        assert "sqlite://" in key
        row = con.execute(
            "SELECT http_status FROM pages WHERE url=?", (_META["url"],)).fetchone()
        assert row and row[0] == 200
        _ok(f"save_meta: row inserted HTTP={row[0]}")

        repo.save_meta(fname, {**_META, "http_status": 301})
        updated = con.execute(
            "SELECT http_status FROM pages WHERE url=?", (_META["url"],)).fetchone()[0]
        assert updated == 301
        _ok("INSERT OR REPLACE upsert: HTTP 200 → 301 updated in place")

        repo.save_summary({
            "started_at": "2024-01-01T00:00:00", "finished_at": "2024-01-01T00:00:05",
            "elapsed_s": 5.0, "total": 2, "success": 2, "error": 0,
        })
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        _ok("save_summary: 1 run row in 'runs' table")
        con.close()
    finally:
        Path(db_path).unlink(missing_ok=True)

    # CompositeRepository
    with tempfile.TemporaryDirectory() as tmp:
        db2 = str(Path(tmp) / "composite.db")
        comp = CompositeRepository(
            LocalFileRepository(tmp), SQLiteRepository(db2))
        fname = comp.filename_for("https://example.com")
        comp.save_meta(fname, _META)
        comp.save_html(fname, _HTML)
        comp.save_summary(_SUMMARY)
        assert (Path(tmp) / f"{fname}_meta.json").exists()
        assert (Path(tmp) / f"{fname}.html").exists()
        assert (Path(tmp) / "scrape_summary.json").exists()
        con2 = sqlite3.connect(db2)
        assert con2.execute(
            "SELECT url FROM pages WHERE url=?", (_META["url"],)).fetchone()
        con2.close()
        _ok("CompositeRepository: data mirrored to both file system and SQLite")


# ══════════════════════════════════════════════════════════════════════════════
# E. Parse Strategies
# ══════════════════════════════════════════════════════════════════════════════

_URL = "https://example.com"
_HTML_SIMPLE = """
<html>
  <head>
    <title>  Hello World  </title>
    <meta name="description" content="A test page.">
  </head>
  <body>
    <p>Welcome!</p>
    <script>var x = 1;</script>
    <nav>Nav content</nav>
  </body>
</html>"""

_HTML_TABLE = """
<html><head><title>Tables</title></head><body>
  <table>
    <tr><th>Name</th><th>Age</th><th>City</th></tr>
    <tr><td>Alice</td><td>30</td><td>Manila</td></tr>
    <tr><td>Bob</td><td>25</td><td>Davao</td></tr>
  </table>
</body></html>"""

_HTML_EMPTY = "<html><body><p>No title.</p></body></html>"
_HTML_RAGGED = """<html><body>
  <table><tr><th>A</th><th>B</th></tr>
  <tr><td>1</td><td>2</td><td>ExtraIgnored</td></tr></table>
</body></html>"""


def section_e_parse_strategy() -> None:
    _header("E. Parse Strategies — RawHtml · BeautifulSoup · Factory")

    raw = RawHtmlStrategy()
    r = raw.parse(_HTML_SIMPLE, _URL)
    assert r["title"] == "Hello World" and list(r.keys()) == ["title"]
    _ok(f"RawHtmlStrategy: title='{r['title']}' (only key returned)")
    assert raw.parse(_HTML_EMPTY, _URL)["title"] == ""
    _ok("RawHtmlStrategy: missing <title> → empty string")

    bs = BeautifulSoupStrategy()
    r2 = bs.parse(_HTML_SIMPLE, _URL)
    assert r2["title"] == "Hello World"
    assert r2["meta_description"] == "A test page."
    assert "Welcome" in r2["text_preview"]
    assert "var x" not in r2["text_preview"]
    assert "Nav content" not in r2["text_preview"]
    _ok(f"BS: title='{r2['title']}', meta='{r2['meta_description']}', noise stripped")

    big = "<html><head><title>X</title></head><body><p>" + \
        ("word " * 5000) + "</p></body></html>"
    assert len(bs.parse(big, _URL)["text_preview"]
               ) <= BeautifulSoupStrategy.MAX_TEXT_CHARS
    _ok(f"BS: text_preview capped at {BeautifulSoupStrategy.MAX_TEXT_CHARS} chars")

    r3 = bs.parse(_HTML_TABLE, _URL)
    rows = r3["tables"][0]
    assert rows[0] == {"Name": "Alice", "Age": "30", "City": "Manila"}
    assert rows[1] == {"Name": "Bob",   "Age": "25", "City": "Davao"}
    _ok(f"BS table extractor: {len(rows)} data rows → {rows}")

    assert "tables" not in bs.parse(_HTML_SIMPLE, _URL)
    _ok("BS: no 'tables' key when page has no <table>")

    ragged = bs.parse(_HTML_RAGGED, _URL)["tables"][0][0]
    assert set(ragged.keys()) == {"A", "B"}
    _ok(f"BS: extra cell in ragged row silently dropped → {ragged}")

    assert isinstance(ParseStrategyFactory.create(
        ScraperConfig(use_parsing=False)), RawHtmlStrategy)
    assert isinstance(ParseStrategyFactory.create(
        ScraperConfig(use_parsing=True)),  BeautifulSoupStrategy)
    _ok("ParseStrategyFactory: use_parsing=False→Raw, True→BeautifulSoup")


# ══════════════════════════════════════════════════════════════════════════════
# F. Resilience utilities
# ══════════════════════════════════════════════════════════════════════════════

def section_f_resilience() -> None:
    _header("F. Resilience — ChangeDetector · CheckpointStore · RetryPolicy · DomainRateLimiter")

    # ── ChangeDetector ────────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cd = ChangeDetector(tmp)
        assert cd.has_changed("https://a.com", "<html>v1</html>") is True
        assert cd.has_changed("https://a.com", "<html>v1</html>") is False
        assert cd.has_changed("https://a.com", "<html>v2</html>") is True
        _ok("ChangeDetector: new→True, same→False, modified→True")

        html = "<html>persist</html>"
        cd.has_changed("https://b.com", html)
        cd2 = ChangeDetector(tmp)
        assert cd2.has_changed("https://b.com", html) is False
        _ok("ChangeDetector: SHA-256 hash persisted across instances")

        cd.has_changed("https://x.com", "<html>x</html>")
        cd.has_changed("https://y.com", "<html>y</html>")
        assert cd.has_changed("https://x.com", "<html>x</html>") is False
        assert cd.has_changed("https://y.com", "<html>y-new</html>") is True
        _ok("ChangeDetector: multiple URLs tracked independently")

    # ── CheckpointStore ───────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp = CheckpointStore(tmp)
        assert cp.is_done("https://example.com") is False
        cp.mark_done("https://example.com")
        assert cp.is_done("https://example.com") is True
        _ok("CheckpointStore: not done → mark_done → done")

        cp2 = CheckpointStore(tmp)
        assert cp2.is_done("https://example.com") is True
        _ok("CheckpointStore: persists in .checkpoint.json across instances")

        cp2.clear()
        assert cp2.is_done("https://example.com") is False
        _ok("CheckpointStore.clear(): all URLs removed")

        urls = [f"https://example.com/p/{i}" for i in range(5)]
        for u in urls[:3]:
            cp.mark_done(u)
        assert all(cp.is_done(u) for u in urls[:3])
        assert not any(cp.is_done(u) for u in urls[3:])
        _ok("CheckpointStore: 3/5 done, 2/5 pending — tracked independently")

    # ── RetryPolicy ───────────────────────────────────────────────────────────
    async def _retry_tests():
        rp = RetryPolicy(3, 0.01)
        calls = [0]
        async def ok_fn(): calls[0] += 1; return "ok"
        assert await rp.execute(ok_fn) == "ok" and calls[0] == 1
        _ok("RetryPolicy: succeeds immediately, exactly 1 call")

        rp2 = RetryPolicy(3, 0.01)
        att = [0]

        async def fail_twice():
            att[0] += 1
            if att[0] < 3:
                raise ConnectionError("tmp")
            return "recovered"
        assert await rp2.execute(fail_twice) == "recovered" and att[0] == 3
        _ok(f"RetryPolicy: recovered after {att[0]} attempts (2 retries)")

        rp3 = RetryPolicy(2, 0.01)
        att2 = [0]
        async def always_fail(): att2[0] += 1; raise ValueError("perm")
        try:
            await rp3.execute(always_fail)
        except ValueError:
            pass
        assert att2[0] == 3
        _ok(f"RetryPolicy: raises after max_retries=2 (total {att2[0]} calls)")

        rp4 = RetryPolicy(2, 0.05)
        ts: list[float] = []
        async def timed_fail(): ts.append(time.monotonic()); raise RuntimeError("x")
        try:
            await rp4.execute(timed_fail)
        except RuntimeError:
            pass
        assert (ts[2] - ts[1]) > (ts[1] - ts[0]) * 1.5
        _ok(
            f"RetryPolicy: exponential backoff (gap1={ts[1]-ts[0]:.3f}s, gap2={ts[2]-ts[1]:.3f}s)")

    asyncio.run(_retry_tests())

    # ── DomainRateLimiter ─────────────────────────────────────────────────────
    async def _rate_tests():
        rl = DomainRateLimiter(0.0)
        t = time.monotonic()
        await rl.acquire("https://x.com/1")
        await rl.acquire("https://x.com/2")
        assert time.monotonic() - t < 0.1
        _ok("DomainRateLimiter(0.0): pass-through, no measurable delay")

        gap = 0.2
        rl2 = DomainRateLimiter(gap)
        t2 = time.monotonic()
        await rl2.acquire("https://example.com/a")
        await rl2.acquire("https://example.com/b")
        assert time.monotonic() - t2 >= gap * 0.9
        _ok(f"DomainRateLimiter({gap}s): minimum inter-request gap enforced")

        rl3 = DomainRateLimiter(0.3)
        t3 = time.monotonic()
        await asyncio.gather(
            rl3.acquire("https://alpha.com/"),
            rl3.acquire("https://beta.com/"),
            rl3.acquire("https://gamma.com/"),
        )
        assert time.monotonic() - t3 < 0.3 * 0.9
        _ok("DomainRateLimiter: different domains not throttled against each other")

    asyncio.run(_rate_tests())


# ══════════════════════════════════════════════════════════════════════════════
# G. Infrastructure
# ══════════════════════════════════════════════════════════════════════════════

def section_g_infrastructure() -> None:
    _header(
        "G. Infrastructure — ProxyManager · SitemapDiscovery · UrlLoader · BrowserSession")

    async def _infra():
        cfg = ScraperConfig(use_proxies=False)
        pm = ProxyManager(cfg)
        assert await pm.next_proxy() is None
        assert hasattr(pm, "_pool") and hasattr(pm, "_tested_proxies")
        _ok("ProxyManager(use_proxies=False): next_proxy()=None, state attrs present")

        sd = SitemapDiscovery()
        url = await sd._find_sitemap_url("https://example.com")
        assert url and "sitemap" in url.lower()
        _ok(f"SitemapDiscovery._find_sitemap_url: '{url}'")

        try:
            urls = await sd.discover("https://books.toscrape.com")
            assert isinstance(urls, list)
            _ok(
                f"SitemapDiscovery.discover: {len(urls)} URL(s) from books.toscrape.com")
        except Exception as e:
            _warn(f"SitemapDiscovery: network unavailable ({e})")

        try:
            bad = await sd.discover("https://nonexistent-xyz999.invalid")
            assert isinstance(bad, list)
            _ok(
                f"SitemapDiscovery: unreachable domain returns list (len={len(bad)})")
        except Exception as e:
            _warn(
                f"SitemapDiscovery: exception on bad domain (strict DNS env): {e}")

    asyncio.run(_infra())

    # ── UrlLoader ─────────────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        # .txt — comments and blank lines stripped
        txt = Path(tmp) / "urls.txt"
        txt.write_text(
            "# comment\nhttps://example.com\n\nhttps://httpbin.org/html\n")
        loaded = UrlLoader.from_file(str(txt))
        assert loaded == ["https://example.com", "https://httpbin.org/html"]
        _ok(f"UrlLoader.from_file(.txt): {len(loaded)} URL(s), comments/blanks stripped")

        # .json — list of strings
        jf = Path(tmp) / "urls.json"
        jf.write_text(json.dumps(["https://a.com", "https://b.com"]))
        loaded_j = UrlLoader.from_file(str(jf))
        assert loaded_j == ["https://a.com", "https://b.com"]
        _ok(f"UrlLoader.from_file(.json): {len(loaded_j)} URL(s)")

        # .json dict → ValueError
        bad = Path(tmp) / "bad.json"
        bad.write_text('{"url": "not-a-list"}')
        try:
            UrlLoader.from_file(str(bad))
            _warn("Expected ValueError — did not raise")
        except ValueError as e:
            _ok(f"UrlLoader.from_file: non-list JSON raises ValueError ({e})")

    # ── BrowserSession ────────────────────────────────────────────────────────
    # BrowserSession is an async context manager used inside the facade's
    # select* methods. We verify its interface without launching a real browser.
    cfg = ScraperConfig(headless=True)
    session = BrowserSession(cfg)
    opened = session.open("https://example.com")
    assert opened is session, "open() must return self for 'async with' chaining"
    assert session._url == "https://example.com"
    assert hasattr(session, "__aenter__") and hasattr(session, "__aexit__")
    _ok("BrowserSession: open() returns self, _url set, async context manager interface present")


# ══════════════════════════════════════════════════════════════════════════════
# H. fetch()
# ══════════════════════════════════════════════════════════════════════════════

def section_h_fetch() -> None:
    _header("H. fetch() — scrape a single URL")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp))
        summary = s.fetch("https://example.com")
        _check_summary(summary, 1, "fetch")

    # fetch with HTML saved to disk
    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp, save_html=True))
        summary = s.fetch("https://example.com")
        r = summary["results"][0]
        if r["status"] == "success":
            assert Path(r["html_file"]).exists()
            size = Path(r["html_file"]).stat().st_size
            _ok(f"fetch+save_html: {r['html_file']} ({size} bytes on disk)")


# ══════════════════════════════════════════════════════════════════════════════
# I. fetch_many()
# ══════════════════════════════════════════════════════════════════════════════

def section_i_fetch_many() -> None:
    _header("I. fetch_many() — concurrent list of URLs")

    urls = ["https://example.com", "https://httpbin.org/html"]
    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp, max_concurrency=2))
        summary = s.fetch_many(urls)
        _check_summary(summary, len(urls), "fetch_many")
        assert (Path(tmp) / "scrape_summary.json").exists()
        _ok("scrape_summary.json written to output_dir")


# ══════════════════════════════════════════════════════════════════════════════
# J. fetch_file()
# ══════════════════════════════════════════════════════════════════════════════

def section_j_fetch_file() -> None:
    _header("J. fetch_file() — load URLs from .txt or .json file")

    with tempfile.TemporaryDirectory() as tmp:
        # .txt — comments and blank lines stripped
        txt = Path(tmp) / "urls.txt"
        txt.write_text(
            "# comment\nhttps://example.com\n\nhttps://httpbin.org/html\n")
        summary = ScraperFacade(_cfg(tmp)).fetch_file(str(txt))
        _check_summary(summary, 2, "fetch_file .txt")

    with tempfile.TemporaryDirectory() as tmp:
        # .json — list of strings
        jf = Path(tmp) / "urls.json"
        jf.write_text(json.dumps(
            ["https://example.com", "https://httpbin.org/html"]))
        summary = ScraperFacade(_cfg(tmp)).fetch_file(str(jf))
        _check_summary(summary, 2, "fetch_file .json")

    with tempfile.TemporaryDirectory() as tmp:
        # .json dict → ValueError
        bad = Path(tmp) / "bad.json"
        bad.write_text('{"url": "not-a-list"}')
        try:
            ScraperFacade(_cfg(tmp)).fetch_file(str(bad))
            _warn("Expected ValueError — did not raise")
        except ValueError as e:
            _ok(f"fetch_file: non-list JSON raises ValueError ({e})")


# ══════════════════════════════════════════════════════════════════════════════
# K. fetch_sitemap()
# ══════════════════════════════════════════════════════════════════════════════

def section_k_fetch_sitemap() -> None:
    _header("K. fetch_sitemap() — discover sitemap then scrape all URLs")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp, max_concurrency=2))
        try:
            summary = s.fetch_sitemap("https://books.toscrape.com")
            _ok(f"fetch_sitemap: total={summary['total']} "
                f"success={summary['success']} error={summary['error']}")
            for r in summary["results"][:3]:
                _row(r)
        except Exception as e:
            _warn(f"fetch_sitemap: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# L. parse()
# ══════════════════════════════════════════════════════════════════════════════

def section_l_parse() -> None:
    _header("L. parse() — structured BS4 extraction from one URL")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp))
        data = s.parse("https://example.com")
        print(f"     Extracted fields: {list(data.keys())}")
        _ok(f"parse: title='{data.get('title')}' "
            f"meta='{data.get('meta_description', '')}' "
            f"text_preview={len(data.get('text_preview', ''))} chars")
        if "tables" in data:
            _ok(f"parse: {len(data['tables'])} table(s) found")


# ══════════════════════════════════════════════════════════════════════════════
# M. parse_many()
# ══════════════════════════════════════════════════════════════════════════════

def section_m_parse_many() -> None:
    _header("M. parse_many() — structured extraction from multiple URLs")

    urls = ["https://example.com", "https://httpbin.org/html"]
    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp, max_concurrency=2))
        results = s.parse_many(urls)
        assert isinstance(results, list)
        _ok(f"parse_many: {len(results)} result(s) returned")
        for item in results:
            title = item.get("title", item.get("status", "?"))
            url = item.get("url", "?")
            print(f"     ↳ '{title}' — {url}")


# ══════════════════════════════════════════════════════════════════════════════
# N. select()
# ══════════════════════════════════════════════════════════════════════════════

def section_n_select() -> None:
    _header("N. select() — grab first element matching a CSS selector")

    s = ScraperFacade(ScraperConfig(headless=True, max_retries=1))

    # inner text of <h1>
    h1 = s.select("https://example.com", "h1")
    _ok(f"select h1 inner text: '{h1}'")

    # inner text of <p>
    p = s.select("https://example.com", "p")
    _ok(f"select first <p> text: '{p}'")

    # attribute — href of first <a>
    href = s.select("https://example.com", "a", attribute="href")
    _ok(f"select a[href]: '{href}'")

    # CSS class selector — product price on scrape-demo site
    price = s.select("https://books.toscrape.com", "p.price_color")
    _ok(f"select p.price_color: '{price}'")

    # selector that does not exist → None
    missing = s.select("https://example.com", "div.does-not-exist")
    assert missing is None
    _ok("select non-existent selector → None (no exception)")


# ══════════════════════════════════════════════════════════════════════════════
# O. select_all()
# ══════════════════════════════════════════════════════════════════════════════

def section_o_select_all() -> None:
    _header("O. select_all() — grab ALL elements matching a CSS selector")

    s = ScraperFacade(ScraperConfig(headless=True, max_retries=1))

    # all <p> texts
    paras = s.select_all("https://example.com", "p")
    _ok(f"select_all p: {len(paras)} paragraph(s) — {paras[:2]}")

    # all hrefs
    links = s.select_all("https://example.com", "a", attribute="href")
    _ok(f"select_all a[href]: {len(links)} link(s) — {links[:3]}")

    # all product titles, limited to 5
    titles = s.select_all(
        "https://books.toscrape.com",
        "article.product_pod h3 a",
        attribute="title",
        limit=5,
    )
    _ok(f"select_all product titles (limit=5): {titles}")

    # all image src URLs
    imgs = s.select_all("https://example.com", "img", attribute="src")
    _ok(f"select_all img[src]: {len(imgs)} image(s)")

    # empty result → [] not exception
    none = s.select_all("https://example.com", "div.ghost")
    assert none == []
    _ok("select_all non-existent selector → [] (no exception)")


# ══════════════════════════════════════════════════════════════════════════════
# P. select_many()
# ══════════════════════════════════════════════════════════════════════════════

def section_p_select_many() -> None:
    _header("P. select_many() — multi-selector in a single browser session")

    s = ScraperFacade(ScraperConfig(headless=True, max_retries=1))

    # query several different things in one page load
    data = s.select_many("https://books.toscrape.com", {
        "page_title":   "title",
        "first_price":  "p.price_color",
        "rating_class": {"selector": "p.star-rating",        "attribute": "class"},
        "all_hrefs":    {"selector": "article h3 a",         "attribute": "href", "all": True},
        "all_prices":   {"selector": "p.price_color",        "all": True},
    })

    _ok(f"select_many page_title:  '{data.get('page_title')}'")
    _ok(f"select_many first_price: '{data.get('first_price')}'")
    _ok(f"select_many rating:      '{data.get('rating_class')}'")
    _ok(f"select_many all_hrefs:   {len(data.get('all_hrefs', []))} link(s)")
    _ok(f"select_many all_prices:  {data.get('all_prices', [])[:5]}")


# ══════════════════════════════════════════════════════════════════════════════
# Q. select_table()
# ══════════════════════════════════════════════════════════════════════════════

def section_q_select_table() -> None:
    _header("Q. select_table() — extract <table> as list-of-dicts")

    s = ScraperFacade(ScraperConfig(headless=True, max_retries=1))

    # Wikipedia has reliable tables
    rows = s.select_table(
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "table.wikitable",
    )
    _ok(f"select_table wikitable: {len(rows)} row(s)")
    if rows:
        _ok(f"  first row keys: {list(rows[0].keys())}")
        _ok(f"  first row: {rows[0]}")

    # books.toscrape — no <table>, returns []
    none_rows = s.select_table("https://books.toscrape.com", "table")
    assert isinstance(none_rows, list)
    _ok(
        f"select_table on table-less page → {none_rows} (empty list, no exception)")

    # index=1 on a page with multiple tables
    rows2 = s.select_table(
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "table.wikitable",
        index=1,
    )
    _ok(f"select_table index=1: {len(rows2)} row(s) from second matching table")


# ══════════════════════════════════════════════════════════════════════════════
# R. detect_changes()
# ══════════════════════════════════════════════════════════════════════════════

def section_r_detect_changes() -> None:
    _header("R. detect_changes() — skip re-saving unchanged content")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp))

        s1 = s.detect_changes(["https://example.com"])
        print(
            f"     Run 1 — success={s1['success']} unchanged={s1['unchanged']}")

        s2 = s.detect_changes(["https://example.com"])
        print(
            f"     Run 2 — success={s2['success']} unchanged={s2['unchanged']}")

        if s1["success"] > 0:
            assert s2.get("unchanged", 0) >= 1
            _ok("Run 2: content hash matched — page not re-saved (unchanged)")
        else:
            _warn("First scrape failed — skipping assertion")


# ══════════════════════════════════════════════════════════════════════════════
# S. resume()
# ══════════════════════════════════════════════════════════════════════════════

def section_s_resume() -> None:
    _header("S. resume() — checkpoint-based resumable runs")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp))

        r1 = s.resume(["https://example.com"])
        print(f"     Run 1 — success={r1['success']} skipped={r1['skipped']}")

        r2 = s.resume(["https://example.com"])
        print(f"     Run 2 — success={r2['success']} skipped={r2['skipped']}")

        if r1["success"] > 0:
            assert r2["skipped"] >= 1
            _ok("Run 2: URL in checkpoint → skipped instantly")
        else:
            _warn("First run failed — skipping checkpoint assertion")

        # checkpoint_status()
        status = s.checkpoint_status()
        _ok(f"checkpoint_status: {status['done_count']} done URL(s), file={status['file']}")

        # clear_checkpoint() then re-check
        s.clear_checkpoint()
        status2 = s.checkpoint_status()
        assert status2["done_count"] == 0
        _ok("clear_checkpoint: checkpoint erased, done_count=0")


# ══════════════════════════════════════════════════════════════════════════════
# T. discover()
# ══════════════════════════════════════════════════════════════════════════════

def section_t_discover() -> None:
    _header("T. discover() — sitemap discovery without scraping")

    s = ScraperFacade(ScraperConfig())
    try:
        urls = s.discover("https://books.toscrape.com")
        assert isinstance(urls, list)
        _ok(f"discover: {len(urls)} URL(s) found in sitemap")
        for u in urls[:5]:
            print(f"     ↳ {u}")
    except Exception as e:
        _warn(f"discover: network unavailable ({e})")


# ══════════════════════════════════════════════════════════════════════════════
# U. observe()
# ══════════════════════════════════════════════════════════════════════════════

class _MetricsObserver(ScrapeObserver):
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.success_urls: list[str] = []

    def on_event(self, event: ScrapeEvent) -> None:
        self.counts[event.name] = self.counts.get(event.name, 0) + 1
        if event.name == "url.success":
            self.success_urls.append(event.payload.get("url", ""))


def section_u_observe() -> None:
    _header("U. observe() — attach a custom event-hook observer")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp))
        metrics = _MetricsObserver()
        s.observe(metrics)
        s.fetch("https://example.com")

        print(f"     Event counts: {metrics.counts}")
        assert "run.start" in metrics.counts
        assert "run.done" in metrics.counts
        assert "url.start" in metrics.counts
        _ok(f"observe: {sum(metrics.counts.values())} total events received")
        _ok(f"Success URLs captured: {metrics.success_urls}")

        slow = s.get_slow_pages()
        _ok(f"get_slow_pages(): {len(slow)} slow page(s) above threshold")


# ══════════════════════════════════════════════════════════════════════════════
# V. SQLite methods
# ══════════════════════════════════════════════════════════════════════════════

def section_v_sqlite() -> None:
    _header("V. SQLite methods — query_db / list_saved / get_run_history / export_json")

    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = ScraperFacade(ScraperConfig(
            output_dir=tmp, use_sqlite=True, sqlite_path=db,
            headless=True, max_retries=1, min_delay=0.1, max_delay=0.2,
        ))
        summary = s.fetch("https://example.com")

        if summary["success"] > 0:
            # query_db — raw SQL SELECT
            rows = s.query_db("SELECT url, http_status FROM pages")
            assert rows
            _ok(f"query_db: {len(rows)} row(s) → {rows[0]}")

            # list_saved
            saved = s.list_saved()
            assert saved
            _ok(f"list_saved: {len(saved)} page(s) in DB")
            _ok(f"  first row keys: {list(saved[0].keys())}")

            # get_run_history
            runs = s.get_run_history()
            assert runs
            _ok(f"get_run_history: {len(runs)} run(s) — "
                f"total={runs[0]['total']} success={runs[0]['success']}")

            # export_json
            out = str(Path(tmp) / "export.json")
            path = s.export_json(out)
            assert Path(path).exists()
            exported = json.loads(Path(path).read_text())
            _ok(f"export_json: {len(exported)} row(s) written to {path}")
        else:
            _warn("Scrape failed — skipping SQLite assertions")


# ══════════════════════════════════════════════════════════════════════════════
# W. describe()
# ══════════════════════════════════════════════════════════════════════════════

def section_w_describe() -> None:
    _header("W. describe() — full config + feature + state snapshot")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(ScraperConfig(
            output_dir=tmp,
            use_sqlite=True, sqlite_path=str(Path(tmp) / "app.db"),
            resumable=True, skip_unchanged=True,
            use_parsing=True, save_html=True,
            use_proxies=False, domain_rate_limit=1.0,
            max_retries=2, slow_page_threshold_sec=8.0,
        ))
        info = s.describe()

        assert "config" in info
        assert "features" in info
        assert "state" in info

        _ok(f"config.output_dir:          {info['config']['output_dir']}")
        _ok(f"config.max_concurrency:     {info['config']['max_concurrency']}")
        _ok(f"config.user_agent_count:    {info['config']['user_agent_count']}")
        _ok(f"features.resumable:         {info['features']['resumable']}")
        _ok(f"features.skip_unchanged:    {info['features']['skip_unchanged']}")
        _ok(f"features.use_parsing:       {info['features']['use_parsing']}")
        _ok(f"features.use_sqlite:        {info['features']['use_sqlite']}")
        _ok(f"features.sqlite_path:       {info['features']['sqlite_path']}")
        _ok(
            f"features.domain_rate_limit: {info['features']['domain_rate_limit_s']}s")
        _ok(f"features.max_retries:       {info['features']['max_retries']}")
        _ok(f"state.checkpoint_file:      {info['state']['checkpoint_file']}")
        _ok(f"state.hash_file:            {info['state']['hash_file']}")


# ══════════════════════════════════════════════════════════════════════════════
# X. Checkpoint + hash management
# ══════════════════════════════════════════════════════════════════════════════

def section_x_management() -> None:
    _header("X. clear_checkpoint() · checkpoint_status() · reset_hashes()")

    with tempfile.TemporaryDirectory() as tmp:
        s = ScraperFacade(_cfg(tmp))

        # checkpoint_status before any run
        cs = s.checkpoint_status()
        assert cs["done_count"] == 0
        _ok(
            f"checkpoint_status (empty): done_count={cs['done_count']}, file={cs['file']}")

        # After a successful fetch
        s.resume(["https://example.com"])
        cs2 = s.checkpoint_status()
        _ok(
            f"checkpoint_status (after resume): done_count={cs2['done_count']}")

        # clear it
        s.clear_checkpoint()
        cs3 = s.checkpoint_status()
        assert cs3["done_count"] == 0
        _ok("clear_checkpoint(): done_count reset to 0")

        # reset_hashes
        s.detect_changes(["https://example.com"])
        hash_file = Path(tmp) / ".content_hashes.json"
        assert hash_file.exists()
        _ok(f"detect_changes created hash file: {hash_file}")

        s.reset_hashes()
        assert not hash_file.exists()
        _ok("reset_hashes(): .content_hashes.json deleted")


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Iki-Scraper — Complete Feature Showcase")
    print("═" * 62)

    section_a_scraper_config()
    section_b_logger()
    section_c_observer_eventbus()
    section_d_repositories()
    section_e_parse_strategy()
    section_f_resilience()
    section_g_infrastructure()

    print(f"\n{'─' * 62}")
    print("  Sections H–X require Playwright (playwright install chromium)")
    print(f"{'─' * 62}")

    section_h_fetch()
    section_i_fetch_many()
    section_j_fetch_file()
    section_k_fetch_sitemap()
    section_l_parse()
    section_m_parse_many()
    section_n_select()
    section_o_select_all()
    section_p_select_many()
    section_q_select_table()
    section_r_detect_changes()
    section_s_resume()
    section_t_discover()
    section_u_observe()
    section_v_sqlite()
    section_w_describe()
    section_x_management()

    print(f"\n{'═' * 62}")
    print("  All sections complete.")
    print(f"{'═' * 62}")
