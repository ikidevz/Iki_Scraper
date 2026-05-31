"""
facade.py — Iki-Scraper public library API
==========================================
Every distinct feature the framework exposes is a **verb-named method**
so callers can compose exactly what they need, never more.

Quick-start
-----------
    from Iki_Scraper.facade import ScraperFacade, ScraperConfig

    s = ScraperFacade()

    # one page
    result = s.fetch("https://example.com")

    # many pages, concurrent
    summary = s.fetch_many(["https://a.com", "https://b.com"])

    # from a .txt / .json file of URLs
    summary = s.fetch_file("urls.txt")

    # auto-discover sitemap then scrape
    summary = s.fetch_sitemap("https://example.com")

    # parse HTML into structured data (title, meta, tables …)
    data = s.parse("https://example.com")

    # detect whether a page changed since last run
    changed = s.detect_changes(["https://example.com"])

    # resume an interrupted run automatically
    summary = s.resume(["https://a.com", "https://b.com"])

    # query the SQLite backend
    rows = s.query_db("SELECT url, http_status FROM pages")

    # inspect slow pages from the last run
    slow = s.get_slow_pages()

    # attach your own observer / event-hook
    s.observe(my_observer)

    # discover sitemap URLs without scraping
    urls = s.discover("https://example.com")

    # clear checkpoint so the next run re-scrapes everything
    s.clear_checkpoint()

    # clear stored content hashes (force re-save next run)
    s.clear_hashes()

    # list all URLs stored in the SQLite DB
    rows = s.list_saved()

    # export SQLite pages table to a JSON file
    path = s.export_json("out.json")
"""

from __future__ import annotations

from Iki_Scraper.core import ScraperOrchestrator, StandardScraper, BrowserSession
from Iki_Scraper.infrastructure import (
    SitemapDiscovery,
    ProxyManager,
    DomainRateLimiter,
    BrowserContextFactory,
    UrlLoader,
)
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
    RetryPolicy,
)
from Iki_Scraper.config import ScraperConfig

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional


import nest_asyncio
nest_asyncio.apply()


log = AppLogger.get()


# ── Internal helper ───────────────────────────────────────────────────────────

def _require_sqlite(cfg: ScraperConfig) -> str:
    """Return the configured sqlite_path, or raise if SQLite is not enabled."""
    if not cfg.use_sqlite:
        raise RuntimeError(
            "SQLite is not enabled. Pass use_sqlite=True to ScraperConfig."
        )
    return cfg.sqlite_path


# ── Facade ────────────────────────────────────────────────────────────────────

class ScraperFacade:
    """
    Single entry-point for the Iki-Scraper library.

    Every public method is a clear **verb** that maps 1-to-1 to a
    user-visible feature.  Internal wiring (EventBus, Orchestrator,
    repositories, etc.) is hidden completely from callers.
    """

    def __init__(self, cfg: Optional[ScraperConfig] = None) -> None:
        self._cfg = cfg or ScraperConfig()
        self._bus = self._build_bus()
        self._slow = SlowPageObserver(self._cfg.slow_page_threshold_sec)
        self._bus.subscribe(self._slow)
        self._orch = self._build_orchestrator()

    # ── internal wiring ───────────────────────────────────────────────────────

    def _build_bus(self) -> EventBus:
        bus = EventBus()
        bus.subscribe(LoggingObserver())
        return bus

    def _build_orchestrator(self) -> ScraperOrchestrator:
        cfg = self._cfg

        file_repo = LocalFileRepository(cfg.output_dir)
        if cfg.use_sqlite:
            repo: OutputRepository = CompositeRepository(
                file_repo, SQLiteRepository(cfg.sqlite_path)
            )
        else:
            repo = file_repo

        scraper = StandardScraper(
            cfg,
            BrowserContextFactory(cfg),
            ProxyManager(cfg),
            DomainRateLimiter(cfg.domain_rate_limit),
            ParseStrategyFactory.create(cfg),
            repo,
            self._bus,
            CheckpointStore(cfg.output_dir) if cfg.resumable else None,
            ChangeDetector(cfg.output_dir) if cfg.skip_unchanged else None,
            RetryPolicy(cfg.max_retries, cfg.retry_base_delay_sec)
            if cfg.max_retries > 0 else None,
        )
        return ScraperOrchestrator(cfg, scraper, repo, self._bus)

    def _run(self, urls: list[str]) -> dict:
        """Execute the orchestrator synchronously."""
        return asyncio.run(self._orch.run(urls))

    # =========================================================================
    # FETCH — launch the browser and scrape
    # =========================================================================

    def fetch(self, url: str) -> dict:
        """
        Scrape a **single URL** with the browser.

        Returns the run-summary dict::

            {
                "total": 1, "success": 1, "error": 0,
                "elapsed_s": 2.3,
                "results": [{"url": ..., "status": "success",
                             "http_status": 200, "size_bytes": ...,
                             "elapsed_s": ..., "meta_file": ...,
                             "html_file": ...}]
            }

        Config knobs used: headless, use_proxies, min_delay/max_delay,
                           max_retries, save_html, use_parsing,
                           resumable, skip_unchanged.
        """
        log.info("fetch: %s", url)
        return self._run([url])

    def fetch_many(self, urls: list[str]) -> dict:
        """
        Scrape **multiple URLs concurrently**.

        Concurrency is controlled by ``ScraperConfig.max_concurrency``
        (default 3).  Respects domain rate-limiting, proxies, and all
        other config flags.

        Args:
            urls: List of fully-qualified URLs to scrape.

        Returns:
            Run-summary dict (same shape as :meth:`fetch`).
        """
        log.info("fetch_many: %d URL(s)", len(urls))
        return self._run(urls)

    def fetch_file(self, filepath: str) -> dict:
        """
        Load URLs from a file and scrape all of them.

        Supported formats:

        * ``.txt`` — one URL per line; lines starting with ``#`` are comments.
        * ``.json`` — a JSON array of URL strings.

        Args:
            filepath: Path to the URL list file.

        Returns:
            Run-summary dict.

        Raises:
            ValueError: If a .json file does not contain a list.
        """
        urls = UrlLoader.from_file(filepath)
        log.info("fetch_file: loaded %d URL(s) from %s", len(urls), filepath)
        return self._run(urls)

    def fetch_sitemap(self, base_url: str) -> dict:
        """
        Auto-discover the sitemap for *base_url*, then scrape every URL in it.

        Discovery order: ``robots.txt`` → ``/sitemap.xml`` fallback.
        Handles sitemap index files recursively.

        Args:
            base_url: Root domain URL, e.g. ``"https://example.com"``.

        Returns:
            Run-summary dict.
        """
        urls = asyncio.run(SitemapDiscovery().discover(base_url))
        log.info("fetch_sitemap: discovered %d URL(s) from %s",
                 len(urls), base_url)
        return self._run(urls)

    # =========================================================================
    # PARSE — extract structured data from a page
    # =========================================================================

    def parse(self, url: str) -> dict:
        """
        Scrape *url* with BeautifulSoup parsing **forced on**, regardless of
        ``ScraperConfig.use_parsing``, and return the structured metadata dict.

        Extracted fields (BeautifulSoupStrategy):

        * ``title``            — ``<title>`` text, whitespace-stripped
        * ``meta_description`` — ``<meta name="description">`` content
        * ``text_preview``     — visible body text (scripts/nav/footer stripped),
                                 capped at 2 000 chars
        * ``tables``           — list of lists-of-dicts (header → cell value)
                                 only present when the page contains ``<table>``

        Args:
            url: The page to fetch and parse.

        Returns:
            Parsed metadata dict for that URL, or ``{}`` on error.
        """
        # Temporarily enable parsing
        original = self._cfg.use_parsing
        self._cfg.use_parsing = True
        self._orch = self._build_orchestrator()   # rebuild with BS strategy
        try:
            summary = self._run([url])
            result = summary["results"][0] if summary["results"] else {}
            if result.get("status") == "success" and result.get("meta_file"):
                return json.loads(Path(result["meta_file"]).read_text())
            return result
        finally:
            self._cfg.use_parsing = original
            self._orch = self._build_orchestrator()

    def parse_many(self, urls: list[str]) -> list[dict]:
        """
        Parse **multiple URLs** and return a list of structured metadata dicts.

        Equivalent to calling :meth:`parse` on each URL but runs them
        concurrently under ``max_concurrency``.

        Args:
            urls: List of URLs to parse.

        Returns:
            List of parsed metadata dicts, one per URL (in result order).
        """
        original = self._cfg.use_parsing
        self._cfg.use_parsing = True
        self._orch = self._build_orchestrator()
        try:
            summary = self._run(urls)
            parsed_list: list[dict] = []
            for r in summary["results"]:
                if r.get("status") == "success" and r.get("meta_file"):
                    try:
                        parsed_list.append(
                            json.loads(Path(r["meta_file"]).read_text())
                        )
                    except Exception:
                        parsed_list.append(r)
                else:
                    parsed_list.append(r)
            return parsed_list
        finally:
            self._cfg.use_parsing = original
            self._orch = self._build_orchestrator()

    # =========================================================================
    # SELECT — live CSS / XPath queries on a real browser page
    # =========================================================================

    def select(
        self,
        url: str,
        selector: str,
        attribute: Optional[str] = None,
        wait: bool = True,
    ) -> Optional[str]:
        """
        Open *url* in the browser, find the **first** element matching
        *selector*, and return its text (or an attribute value).

        Examples::

            title = facade.select("https://example.com", "h1")
            cls   = facade.select("https://example.com", "h1", attribute="class")
            href  = facade.select("https://example.com", "a",  attribute="href")

        Args:
            url:       The page to open.
            selector:  Any CSS selector or XPath starting with ``"xpath="``.
            attribute: If given, return that HTML attribute instead of inner text.
            wait:      If ``True`` (default), wait up to ``page_timeout_ms``
                       for the element to appear in the DOM before querying.

        Returns:
            The matched text / attribute value, or ``None`` if not found.
        """
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        async def _run():
            async with BrowserSession(self._cfg).open(url) as page:
                if wait:
                    try:
                        el = await page.wait_for_selector(
                            selector, timeout=self._cfg.page_timeout_ms
                        )
                    except PlaywrightTimeoutError:
                        return None
                else:
                    el = await page.query_selector(selector)

                if el is None:
                    return None
                if attribute:
                    return await el.get_attribute(attribute)
                return (await el.inner_text()).strip()

        result = asyncio.run(_run())
        log.info("select(%r, %r) → %r", url, selector, result)
        return result

    def select_all(
        self,
        url: str,
        selector: str,
        attribute: Optional[str] = None,
        wait: bool = True,
        limit: Optional[int] = None,
    ) -> list[str]:
        """
        Open *url* in the browser, find **all** elements matching *selector*,
        and return their text (or attribute values) as a list.

        Examples::

            paragraphs = facade.select_all("https://example.com", "p")
            links      = facade.select_all("https://example.com", "a", attribute="href")
            titles     = facade.select_all(
                "https://books.toscrape.com", "article.product_pod h3 a",
                attribute="title", limit=5
            )

        Args:
            url:       The page to open.
            selector:  Any CSS selector or XPath starting with ``"xpath="``.
            attribute: If given, return that HTML attribute for each element.
            wait:      If ``True`` (default), wait for the first matching element.
            limit:     If given, return at most *limit* results.

        Returns:
            List of strings (text or attribute values), empty list if none found.
        """
        async def _run():
            async with BrowserSession(self._cfg).open(url) as page:
                if wait:
                    try:
                        await page.wait_for_selector(
                            selector, timeout=self._cfg.page_timeout_ms
                        )
                    except Exception:
                        return []
                elements = await page.query_selector_all(selector)
                if limit is not None:
                    elements = elements[:limit]
                results: list[str] = []
                for el in elements:
                    val = (
                        await el.get_attribute(attribute)
                        if attribute
                        else (await el.inner_text()).strip()
                    )
                    if val is not None:
                        results.append(val)
                return results

        results = asyncio.run(_run())
        log.info("select_all(%r, %r) → %d result(s)",
                 url, selector, len(results))
        return results

    def select_many(
        self,
        url: str,
        selectors: dict[str, str | dict],
    ) -> dict[str, Any]:
        """
        Open *url* **once** and query multiple selectors in a single browser
        session.  More efficient than calling :meth:`select` repeatedly.

        *selectors* maps a label to either:

        * a plain CSS selector string → returns inner text of first match
        * a dict ``{"selector": "...", "attribute": "...", "all": True/False}``
          → full control per field

        Example::

            data = facade.select_many("https://books.toscrape.com/", {
                "title":     "h1",
                "price":     "p.price_color",
                "rating":    {"selector": "p.star-rating", "attribute": "class"},
                "all_links": {"selector": "a", "attribute": "href", "all": True},
            })

        Args:
            url:       The page to open.
            selectors: Mapping of label → selector spec (see above).

        Returns:
            Dict mapping each label to its result (str, list, or None).
        """
        async def _run():
            async with BrowserSession(self._cfg).open(url) as page:
                output: dict[str, Any] = {}
                for label, spec in selectors.items():
                    if isinstance(spec, str):
                        css, attr, all_ = spec, None, False
                    else:
                        css = spec["selector"]
                        attr = spec.get("attribute")
                        all_ = spec.get("all", False)

                    if all_:
                        elements = await page.query_selector_all(css)
                        vals: list[str] = []
                        for el in elements:
                            v = (
                                await el.get_attribute(attr)
                                if attr
                                else (await el.inner_text()).strip()
                            )
                            if v is not None:
                                vals.append(v)
                        output[label] = vals
                    else:
                        el = await page.query_selector(css)
                        if el is None:
                            output[label] = None
                        elif attr:
                            output[label] = await el.get_attribute(attr)
                        else:
                            output[label] = (await el.inner_text()).strip()

                return output

        result = asyncio.run(_run())
        log.info("select_many(%r) → %d field(s)", url, len(result))
        return result

    def select_table(
        self,
        url: str,
        selector: str = "table",
        index: int = 0,
    ) -> list[dict]:
        """
        Open *url* and extract a specific HTML ``<table>`` as a list of dicts,
        using the first ``<tr>`` as headers.

        Example::

            rows = facade.select_table(
                "https://en.wikipedia.org/wiki/Python_(programming_language)",
                "table.wikitable",
            )

        Args:
            url:      The page to open.
            selector: CSS selector that matches ``<table>`` elements (default ``"table"``).
            index:    Which matched table to extract (0-based, default 0).

        Returns:
            List of row dicts (header → cell text).  Empty list if not found.
        """
        async def _run():
            async with BrowserSession(self._cfg).open(url) as page:
                tables = await page.query_selector_all(selector)
                if not tables or index >= len(tables):
                    return []
                table = tables[index]

                header_els = await table.query_selector_all("tr:first-child th")
                if not header_els:
                    header_els = await table.query_selector_all("tr:first-child td")
                headers = [(await h.inner_text()).strip() for h in header_els]
                if not headers:
                    return []

                rows_out: list[dict] = []
                row_els = await table.query_selector_all("tr:not(:first-child)")
                for row_el in row_els:
                    cells = await row_el.query_selector_all("td")
                    cell_texts = [(await c.inner_text()).strip() for c in cells]
                    rows_out.append(dict(zip(headers, cell_texts)))
                return rows_out

        rows = asyncio.run(_run())
        log.info("select_table(%r, %r, index=%d) → %d row(s)",
                 url, selector, index, len(rows))
        return rows

    # =========================================================================
    # DETECT — change detection across runs
    # =========================================================================

    def detect_changes(self, urls: list[str]) -> dict:
        """
        Scrape *urls* with **skip-unchanged forced on**.

        Pages whose HTML hash matches the stored hash from the previous run
        return ``status="unchanged"`` and are not re-saved to disk/DB.

        Args:
            urls: List of URLs to check.

        Returns:
            Run-summary dict.
        """
        original = self._cfg.skip_unchanged
        self._cfg.skip_unchanged = True
        self._orch = self._build_orchestrator()
        try:
            return self._run(urls)
        finally:
            self._cfg.skip_unchanged = original
            self._orch = self._build_orchestrator()

    def reset_hashes(self) -> None:
        """
        Delete all stored content hashes so the **next** :meth:`detect_changes`
        treats every page as new.

        The hash file lives at ``<output_dir>/.content_hashes.json``.
        """
        p = Path(self._cfg.output_dir) / ".content_hashes.json"
        if p.exists():
            p.unlink()
            log.info("reset_hashes: removed %s", p)
        else:
            log.info("reset_hashes: nothing to remove")

    # =========================================================================
    # RESUME — checkpoint-based resumable runs
    # =========================================================================

    def resume(self, urls: list[str]) -> dict:
        """
        Scrape *urls* with **resumable mode forced on**.

        URLs already marked as done in ``.checkpoint.json`` are skipped
        instantly (``status="skipped"``).

        Args:
            urls: Full list of URLs for the job.

        Returns:
            Run-summary dict.
        """
        original = self._cfg.resumable
        self._cfg.resumable = True
        self._orch = self._build_orchestrator()
        try:
            return self._run(urls)
        finally:
            self._cfg.resumable = original
            self._orch = self._build_orchestrator()

    def clear_checkpoint(self) -> None:
        """
        Erase the checkpoint store so the next :meth:`resume` call re-scrapes
        all URLs from scratch.
        """
        cp = CheckpointStore(self._cfg.output_dir)
        cp.clear()
        log.info("clear_checkpoint: checkpoint erased")

    def checkpoint_status(self) -> dict:
        """
        Return the current checkpoint state without modifying it.

        Returns:
            dict with keys ``"done_count"``, ``"done_urls"``, ``"file"``.
        """
        path = Path(self._cfg.output_dir) / ".checkpoint.json"
        done: list[str] = []
        if path.exists():
            try:
                done = json.loads(path.read_text())
            except Exception:
                pass
        return {
            "done_count": len(done),
            "done_urls":  sorted(done),
            "file":       str(path.resolve()),
        }

    # =========================================================================
    # DISCOVER — sitemap / URL discovery (no scraping)
    # =========================================================================

    def discover(self, base_url: str) -> list[str]:
        """
        Discover all URLs in the sitemap of *base_url* **without** scraping.

        Args:
            base_url: Root domain URL, e.g. ``"https://example.com"``.

        Returns:
            Deduplicated list of page URLs found in the sitemap.
        """
        urls = asyncio.run(SitemapDiscovery().discover(base_url))
        log.info("discover: %d URL(s) found for %s", len(urls), base_url)
        return urls

    # =========================================================================
    # OBSERVE — event bus / observer hooks
    # =========================================================================

    def observe(self, observer: ScrapeObserver) -> None:
        """
        Attach a custom :class:`ScrapeObserver` to the event bus.

        Events: ``"run.start"``, ``"run.done"``, ``"url.start"``,
        ``"url.success"``, ``"url.error"``, ``"url.skip"``.

        Args:
            observer: Any object subclassing :class:`ScrapeObserver`.
        """
        self._bus.subscribe(observer)
        log.info("observe: registered %s", type(observer).__name__)

    def get_slow_pages(self) -> list[dict]:
        """
        Return pages from the **last run** whose load time exceeded
        ``ScraperConfig.slow_page_threshold_sec`` (default 10 s).

        Returns:
            List of ``{"url": str, "elapsed_s": float}`` dicts.
        """
        return self._slow.slow_pages

    # =========================================================================
    # STORE — SQLite query / export
    # =========================================================================

    def query_db(self, sql: str, params: tuple = ()) -> list[dict]:
        """
        Execute a raw SQL **SELECT** against the SQLite backend.

        Requires ``ScraperConfig(use_sqlite=True)``.

        Args:
            sql:    A SELECT statement.
            params: Optional positional parameters.

        Returns:
            List of row dicts.

        Raises:
            RuntimeError: If SQLite is not enabled in config.
        """
        db = _require_sqlite(self._cfg)
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()
        return rows

    def list_saved(self) -> list[dict]:
        """
        Return every row from the SQLite ``pages`` table as a list of dicts.

        Requires ``ScraperConfig(use_sqlite=True)``.
        """
        return self.query_db(
            "SELECT url, filename, timestamp, http_status, size_bytes "
            "FROM pages ORDER BY timestamp DESC"
        )

    def get_run_history(self) -> list[dict]:
        """
        Return every row from the SQLite ``runs`` table, newest first.

        Requires ``ScraperConfig(use_sqlite=True)``.
        """
        return self.query_db(
            "SELECT id, started_at, finished_at, elapsed_s, total, success, error "
            "FROM runs ORDER BY id DESC"
        )

    def export_json(self, dest: str) -> str:
        """
        Export every row in the SQLite ``pages`` table to a JSON file.

        Requires ``ScraperConfig(use_sqlite=True)``.

        Args:
            dest: File path for the exported JSON (will be overwritten).

        Returns:
            Absolute path to the written file.
        """
        rows = self.list_saved()
        path = Path(dest)
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("export_json: %d row(s) → %s", len(rows), path.resolve())
        return str(path.resolve())

    # =========================================================================
    # CONFIG — runtime config inspection helpers
    # =========================================================================

    def describe(self) -> dict:
        """
        Return a human-readable summary of the active configuration,
        all enabled features, and library state.

        Returns:
            Dict with sections ``"config"``, ``"features"``, ``"state"``.
        """
        cfg = self._cfg
        return {
            "config": {
                "output_dir":             cfg.output_dir,
                "max_concurrency":        cfg.max_concurrency,
                "headless":               cfg.headless,
                "min_delay":              cfg.min_delay,
                "max_delay":              cfg.max_delay,
                "page_timeout_ms":        cfg.page_timeout_ms,
                "viewport":               cfg.viewport,
                "scroll_step_px":         cfg.scroll_step_px,
                "scroll_interval_sec":    cfg.scroll_interval_sec,
                "user_agent_count":       len(cfg.user_agents),
            },
            "features": {
                "resumable":              cfg.resumable,
                "skip_unchanged":         cfg.skip_unchanged,
                "use_parsing":            cfg.use_parsing,
                "save_html":              cfg.save_html,
                "use_sqlite":             cfg.use_sqlite,
                "sqlite_path":            cfg.sqlite_path if cfg.use_sqlite else None,
                "use_proxies":            cfg.use_proxies,
                "proxy_refresh_every":    cfg.proxy_refresh_every,
                "domain_rate_limit_s":    cfg.domain_rate_limit,
                "max_retries":            cfg.max_retries,
                "retry_base_delay_sec":   cfg.retry_base_delay_sec,
                "slow_page_threshold_s":  cfg.slow_page_threshold_sec,
            },
            "state": {
                "slow_pages_recorded":    len(self._slow.slow_pages),
                "checkpoint_file":        str(
                    (Path(cfg.output_dir) / ".checkpoint.json").resolve()
                ),
                "hash_file":              str(
                    (Path(cfg.output_dir) / ".content_hashes.json").resolve()
                ),
            },
        }

    # =========================================================================
    # Backward-compatible aliases (kept so old code doesn't break)
    # =========================================================================

    def scrape_one(self, url: str) -> dict:
        """Alias for :meth:`fetch`. Kept for backward compatibility."""
        return self.fetch(url)

    def scrape_many(self, urls: list[str]) -> dict:
        """Alias for :meth:`fetch_many`. Kept for backward compatibility."""
        return self.fetch_many(urls)

    def scrape_file(self, filepath: str) -> dict:
        """Alias for :meth:`fetch_file`. Kept for backward compatibility."""
        return self.fetch_file(filepath)

    def scrape_sitemap(self, base_url: str) -> dict:
        """Alias for :meth:`fetch_sitemap`. Kept for backward compatibility."""
        return self.fetch_sitemap(base_url)

    async def discover_sitemap(self, base_url: str) -> list[str]:
        """Async alias for :meth:`discover`. Kept for backward compatibility."""
        return await SitemapDiscovery().discover(base_url)

    def add_observer(self, observer: ScrapeObserver) -> None:
        """Alias for :meth:`observe`. Kept for backward compatibility."""
        return self.observe(observer)

    @property
    def slow_pages(self) -> list[dict]:
        """Property alias for :meth:`get_slow_pages`. Backward compatible."""
        return self.get_slow_pages()
