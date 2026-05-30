"""
test_unit.py — Unit tests (no browser, no network)
===================================================
Groups:
    TestScraperConfig     — config defaults & overrides
    TestAppLogger         — singleton, type, instantiation guard
    TestEventBus          — pub/sub, error isolation
    TestObservers         — LoggingObserver, SlowPageObserver
    TestLocalFileRepo     — filename_for, save_html/meta/summary, mkdir
    TestSQLiteRepo        — schema, save_meta upsert, save_summary
    TestCompositeRepo     — dual-write to file + SQLite
    TestRawHtmlStrategy   — title extraction
    TestBeautifulSoupStrategy — title, meta, text, tables, noise, truncation
    TestParseStrategyFactory  — factory dispatch
"""

import json
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path

from Iki_Scraper.config import ScraperConfig
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


# ── Helpers ────────────────────────────────────────────────────────────────────

class RecordingObserver(ScrapeObserver):
    def __init__(self): self.received: list[ScrapeEvent] = []
    def on_event(self, e: ScrapeEvent) -> None: self.received.append(e)


class BrokenObserver(ScrapeObserver):
    def on_event(self, e: ScrapeEvent) -> None: raise RuntimeError("boom")


SAMPLE_META = {
    "url": "https://example.com/page",
    "timestamp": "2024-01-01T00:00:00+00:00",
    "http_status": 200,
    "size_bytes": 1024,
    "title": "Example Page",
    "user_agent": "TestBot/1.0",
    "proxy": None,
}
SAMPLE_HTML = "<html><body><h1>Hello</h1></body></html>"
SAMPLE_SUMMARY = {"total": 1, "success": 1, "error": 0, "elapsed_s": 2.5}

HTML_SIMPLE = """
<html>
  <head>
    <title>  Hello World  </title>
    <meta name="description" content="A test page for Iki-Scraper.">
  </head>
  <body>
    <p>Welcome to the test page.</p>
    <script>var x = 1;</script>
    <nav>Nav content</nav>
  </body>
</html>"""

HTML_TABLE = """
<html><head><title>Table Page</title></head><body>
  <table>
    <tr><th>Name</th><th>Age</th><th>City</th></tr>
    <tr><td>Alice</td><td>30</td><td>Manila</td></tr>
    <tr><td>Bob</td><td>25</td><td>Davao</td></tr>
  </table>
</body></html>"""

HTML_NO_TITLE = "<html><body><p>No title.</p></body></html>"
HTML_RAGGED = """<html><body>
  <table><tr><th>A</th><th>B</th></tr>
  <tr><td>1</td><td>2</td><td>Ignored</td></tr></table>
</body></html>"""
URL = "https://example.com"


# ══════════════════════════════════════════════════════════════════════════════
# ScraperConfig
# ══════════════════════════════════════════════════════════════════════════════

class TestScraperConfig(unittest.TestCase):

    def test_default_values(self):
        cfg = ScraperConfig()
        self.assertEqual(cfg.output_dir, "scraper_output")
        self.assertEqual(cfg.max_concurrency, 3)
        self.assertTrue(cfg.headless)
        self.assertFalse(cfg.use_proxies)
        self.assertEqual(cfg.max_retries, 3)
        self.assertFalse(cfg.use_sqlite)
        self.assertFalse(cfg.resumable)
        self.assertFalse(cfg.skip_unchanged)
        self.assertEqual(cfg.domain_rate_limit, 0.0)
        self.assertEqual(cfg.slow_page_threshold_sec, 10.0)
        self.assertFalse(cfg.use_parsing)
        self.assertFalse(cfg.save_html)
        self.assertIsInstance(cfg.user_agents, list)
        self.assertGreaterEqual(len(cfg.user_agents), 10)
        self.assertEqual(cfg.viewport, {"width": 1366, "height": 768})

    def test_overrides(self):
        cfg = ScraperConfig(
            output_dir="out", max_concurrency=5, headless=False,
            use_proxies=True, max_retries=0, min_delay=0.5, max_delay=2.0,
            use_sqlite=True, sqlite_path="db.db", resumable=True,
            skip_unchanged=True, domain_rate_limit=1.5,
            slow_page_threshold_sec=5.0, use_parsing=True, save_html=True,
        )
        self.assertEqual(cfg.output_dir, "out")
        self.assertEqual(cfg.max_concurrency, 5)
        self.assertFalse(cfg.headless)
        self.assertTrue(cfg.use_proxies)
        self.assertEqual(cfg.max_retries, 0)
        self.assertEqual(cfg.min_delay, 0.5)
        self.assertEqual(cfg.max_delay, 2.0)
        self.assertTrue(cfg.use_sqlite)
        self.assertEqual(cfg.sqlite_path, "db.db")
        self.assertTrue(cfg.resumable)
        self.assertTrue(cfg.skip_unchanged)
        self.assertEqual(cfg.domain_rate_limit, 1.5)
        self.assertEqual(cfg.slow_page_threshold_sec, 5.0)
        self.assertTrue(cfg.use_parsing)
        self.assertTrue(cfg.save_html)

    def test_custom_user_agents(self):
        uas = ["MyBot/1.0", "TestBot/2.0"]
        cfg = ScraperConfig(user_agents=uas)
        self.assertEqual(cfg.user_agents, uas)

    def test_custom_viewport(self):
        cfg = ScraperConfig(viewport={"width": 1920, "height": 1080})
        self.assertEqual(cfg.viewport["width"], 1920)


# ══════════════════════════════════════════════════════════════════════════════
# AppLogger
# ══════════════════════════════════════════════════════════════════════════════

class TestAppLogger(unittest.TestCase):

    def test_singleton(self):
        self.assertIs(AppLogger.get(), AppLogger.get())

    def test_is_logging_logger(self):
        log = AppLogger.get()
        self.assertIsInstance(log, logging.Logger)
        self.assertEqual(log.name, "Iki_Scraper")

    def test_direct_instantiation_raises(self):
        with self.assertRaises(TypeError):
            AppLogger()

    def test_can_log(self):
        log = AppLogger.get()
        # Should not raise
        log.info("unit-test INFO")
        log.warning("unit-test WARNING")
        log.debug("unit-test DEBUG")


# ══════════════════════════════════════════════════════════════════════════════
# EventBus
# ══════════════════════════════════════════════════════════════════════════════

class TestEventBus(unittest.TestCase):

    def test_scrape_event_fields(self):
        ev = ScrapeEvent("url.start", {"message": "hello"})
        self.assertEqual(ev.name, "url.start")
        self.assertEqual(ev.payload["message"], "hello")
        self.assertTrue(ev.timestamp)

    def test_subscribe_and_publish(self):
        bus = EventBus()
        rec = RecordingObserver()
        bus.subscribe(rec)
        bus.publish("url.start", message="go")
        bus.publish("url.success", url=URL, elapsed_s=1.5, message="done")
        self.assertEqual(len(rec.received), 2)
        self.assertEqual(rec.received[0].name, "url.start")
        self.assertEqual(rec.received[1].payload["elapsed_s"], 1.5)

    def test_multiple_observers(self):
        bus = EventBus()
        r1, r2 = RecordingObserver(), RecordingObserver()
        bus.subscribe(r1)
        bus.subscribe(r2)
        bus.publish("run.start", message="go")
        self.assertEqual(len(r1.received), 1)
        self.assertEqual(len(r2.received), 1)

    def test_broken_observer_isolated(self):
        bus = EventBus()
        bus.subscribe(BrokenObserver())
        healthy = RecordingObserver()
        bus.subscribe(healthy)
        bus.publish("url.start", message="test")
        self.assertEqual(len(healthy.received), 1)

    def test_no_observers(self):
        bus = EventBus()
        # should not raise
        bus.publish("url.start", message="nothing to receive")


# ══════════════════════════════════════════════════════════════════════════════
# Observers
# ══════════════════════════════════════════════════════════════════════════════

class TestObservers(unittest.TestCase):

    def _bus_with(self, obs):
        bus = EventBus()
        bus.subscribe(obs)
        return bus

    def test_logging_observer_all_event_names(self):
        bus = self._bus_with(LoggingObserver())
        for name in ("url.start", "url.success", "url.error", "url.skip", "run.done", "run.start"):
            bus.publish(name, message=f"test {name}", url=URL, elapsed_s=1.0)
        # No assertion needed — absence of exception is the test

    def test_slow_page_observer_below_threshold(self):
        obs = SlowPageObserver(threshold_s=10.0)
        self._bus_with(obs).publish(
            "url.success", url=URL, elapsed_s=2.0, message="ok")
        self.assertEqual(len(obs.slow_pages), 0)

    def test_slow_page_observer_above_threshold(self):
        obs = SlowPageObserver(threshold_s=5.0)
        self._bus_with(obs).publish(
            "url.success", url="https://slow.com", elapsed_s=12.3, message="ok")
        self.assertEqual(len(obs.slow_pages), 1)
        self.assertEqual(obs.slow_pages[0]["url"], "https://slow.com")
        self.assertEqual(obs.slow_pages[0]["elapsed_s"], 12.3)

    def test_slow_page_observer_exact_threshold(self):
        obs = SlowPageObserver(threshold_s=5.0)
        self._bus_with(obs).publish(
            "url.success", url=URL, elapsed_s=5.0, message="ok")
        self.assertEqual(len(obs.slow_pages), 1)

    def test_slow_page_observer_ignores_non_success(self):
        obs = SlowPageObserver(threshold_s=1.0)
        bus = self._bus_with(obs)
        bus.publish("url.error",   url=URL, elapsed_s=99.0, message="fail")
        bus.publish("url.start",   url=URL, elapsed_s=99.0, message="start")
        self.assertEqual(len(obs.slow_pages), 0)

    def test_slow_page_accumulates_multiple(self):
        obs = SlowPageObserver(threshold_s=5.0)
        bus = self._bus_with(obs)
        for i in range(3):
            bus.publish(
                "url.success", url=f"https://slow{i}.com", elapsed_s=10.0 + i, message="ok")
        self.assertEqual(len(obs.slow_pages), 3)


# ══════════════════════════════════════════════════════════════════════════════
# LocalFileRepository
# ══════════════════════════════════════════════════════════════════════════════

class TestLocalFileRepo(unittest.TestCase):

    def test_filename_for_strips_scheme_and_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = LocalFileRepository(tmp)
            name = repo.filename_for("https://example.com/path?q=1")
            self.assertNotIn("https", name)
            self.assertNotIn("/", name)
            self.assertLessEqual(len(name), 120)

    def test_save_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = LocalFileRepository(tmp)
            fname = repo.filename_for(URL)
            path = repo.save_html(fname, SAMPLE_HTML)
            self.assertTrue(Path(path).exists())
            self.assertEqual(Path(path).read_text(), SAMPLE_HTML)

    def test_save_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = LocalFileRepository(tmp)
            fname = repo.filename_for(URL)
            path = repo.save_meta(fname, SAMPLE_META)
            self.assertTrue(Path(path).exists())
            data = json.loads(Path(path).read_text())
            self.assertEqual(data["url"], SAMPLE_META["url"])
            self.assertEqual(data["http_status"], 200)

    def test_save_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = LocalFileRepository(tmp)
            path = repo.save_summary(SAMPLE_SUMMARY)
            self.assertTrue(Path(path).exists())
            self.assertEqual(json.loads(Path(path).read_text())["total"], 1)

    def test_creates_nested_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = str(Path(tmp) / "a" / "b" / "c")
            LocalFileRepository(nested)
            self.assertTrue(Path(nested).exists())


# ══════════════════════════════════════════════════════════════════════════════
# SQLiteRepository
# ══════════════════════════════════════════════════════════════════════════════

class TestSQLiteRepo(unittest.TestCase):

    def _make_db(self):
        import tempfile as _tf
        f = _tf.NamedTemporaryFile(suffix=".db", delete=False)
        path = f.name
        f.close()
        return path

    def test_schema_created(self):
        path = self._make_db()
        try:
            SQLiteRepository(path)
            con = sqlite3.connect(path)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("pages", tables)
            self.assertIn("runs", tables)
            con.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_meta_inserts_row(self):
        path = self._make_db()
        try:
            repo = SQLiteRepository(path)
            fname = repo.filename_for(URL)
            key = repo.save_meta(fname, SAMPLE_META)
            self.assertIn("sqlite://", key)
            con = sqlite3.connect(path)
            row = con.execute("SELECT http_status FROM pages WHERE url=?",
                              (SAMPLE_META["url"],)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 200)
            con.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_meta_upsert(self):
        path = self._make_db()
        try:
            repo = SQLiteRepository(path)
            fname = repo.filename_for(URL)
            repo.save_meta(fname, SAMPLE_META)
            repo.save_meta(fname, {**SAMPLE_META, "http_status": 301})
            con = sqlite3.connect(path)
            status = con.execute("SELECT http_status FROM pages WHERE url=?",
                                 (SAMPLE_META["url"],)).fetchone()[0]
            self.assertEqual(status, 301)
            con.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_summary_inserts_run(self):
        path = self._make_db()
        try:
            repo = SQLiteRepository(path)
            repo.save_summary({
                "started_at": "2024-01-01T00:00:00", "finished_at": "2024-01-01T00:00:05",
                "elapsed_s": 5.0, "total": 2, "success": 2, "error": 0,
            })
            con = sqlite3.connect(path)
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM runs").fetchone()[0], 1)
            con.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_filename_for(self):
        path = self._make_db()
        try:
            repo = SQLiteRepository(path)
            name = repo.filename_for("https://example.com/path?q=1")
            self.assertNotIn("https", name)
            self.assertLessEqual(len(name), 120)
        finally:
            Path(path).unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# CompositeRepository
# ══════════════════════════════════════════════════════════════════════════════

class TestCompositeRepo(unittest.TestCase):

    def test_writes_to_both_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            composite = CompositeRepository(
                LocalFileRepository(tmp),
                SQLiteRepository(db_path),
            )
            fname = composite.filename_for(URL)
            composite.save_meta(fname, SAMPLE_META)
            composite.save_html(fname, SAMPLE_HTML)
            composite.save_summary(SAMPLE_SUMMARY)

            self.assertTrue((Path(tmp) / f"{fname}_meta.json").exists())
            self.assertTrue((Path(tmp) / f"{fname}.html").exists())
            self.assertTrue((Path(tmp) / "scrape_summary.json").exists())

            con = sqlite3.connect(db_path)
            row = con.execute("SELECT url FROM pages WHERE url=?",
                              (SAMPLE_META["url"],)).fetchone()
            self.assertIsNotNone(row)
            con.close()


# ══════════════════════════════════════════════════════════════════════════════
# RawHtmlStrategy
# ══════════════════════════════════════════════════════════════════════════════

class TestRawHtmlStrategy(unittest.TestCase):

    def setUp(self): self.s = RawHtmlStrategy()

    def test_extracts_title(self):
        r = self.s.parse(HTML_SIMPLE, URL)
        self.assertEqual(r["title"], "Hello World")

    def test_only_title_key_returned(self):
        r = self.s.parse(HTML_SIMPLE, URL)
        self.assertEqual(list(r.keys()), ["title"])

    def test_empty_title_on_missing(self):
        self.assertEqual(self.s.parse(HTML_NO_TITLE, URL)["title"], "")

    def test_strips_whitespace_from_title(self):
        html = "<html><head><title>  Padded  </title></head></html>"
        self.assertEqual(self.s.parse(html, URL)["title"], "Padded")


# ══════════════════════════════════════════════════════════════════════════════
# BeautifulSoupStrategy
# ══════════════════════════════════════════════════════════════════════════════

class TestBeautifulSoupStrategy(unittest.TestCase):

    def setUp(self): self.s = BeautifulSoupStrategy()

    def test_title_and_meta_description(self):
        r = self.s.parse(HTML_SIMPLE, URL)
        self.assertEqual(r["title"], "Hello World")
        self.assertEqual(r["meta_description"], "A test page for Iki-Scraper.")

    def test_text_preview_excludes_script_nav(self):
        r = self.s.parse(HTML_SIMPLE, URL)
        self.assertIn("Welcome", r["text_preview"])
        self.assertNotIn("var x", r["text_preview"])
        self.assertNotIn("Nav content", r["text_preview"])

    def test_text_preview_truncated_at_max(self):
        big = ("<html><head><title>X</title></head><body><p>"
               + ("word " * 5000) + "</p></body></html>")
        r = self.s.parse(big, URL)
        self.assertLessEqual(len(r["text_preview"]),
                             BeautifulSoupStrategy.MAX_TEXT_CHARS)

    def test_table_extraction(self):
        r = self.s.parse(HTML_TABLE, URL)
        self.assertIn("tables", r)
        rows = r["tables"][0]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0], {"Name": "Alice", "Age": "30", "City": "Manila"})
        self.assertEqual(
            rows[1], {"Name": "Bob",   "Age": "25", "City": "Davao"})

    def test_no_tables_key_when_none_present(self):
        r = self.s.parse(HTML_SIMPLE, URL)
        self.assertNotIn("tables", r)

    def test_ragged_table_extra_cell_ignored(self):
        r = self.s.parse(HTML_RAGGED, URL)
        row = r["tables"][0][0]
        self.assertEqual(set(row.keys()), {"A", "B"})

    def test_missing_meta_description_empty_string(self):
        r = self.s.parse(HTML_NO_TITLE, URL)
        self.assertEqual(r["meta_description"], "")


# ══════════════════════════════════════════════════════════════════════════════
# ParseStrategyFactory
# ══════════════════════════════════════════════════════════════════════════════

class TestParseStrategyFactory(unittest.TestCase):

    def test_raw_when_parsing_disabled(self):
        self.assertIsInstance(
            ParseStrategyFactory.create(ScraperConfig(use_parsing=False)),
            RawHtmlStrategy,
        )

    def test_bs_when_parsing_enabled(self):
        self.assertIsInstance(
            ParseStrategyFactory.create(ScraperConfig(use_parsing=True)),
            BeautifulSoupStrategy,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
