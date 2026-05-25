# 🕷️ Iki Scrapper - A tool for data scrapers with Advanced asynchronous web scraping framework with proxy rotation, human behavior simulation, and robust architecture.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Playwright](https://img.shields.io/badge/Playwright-async-green?style=flat-square)
![Patterns](https://img.shields.io/badge/Design%20Patterns-7-purple?style=flat-square)
![Features](https://img.shields.io/badge/New%20Features-9-coral?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-67%20passing-teal?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)

> Production-ready async web scraper — OOP, 7 design patterns, 9 new features.
> Human-like behaviour · proxy rotation · resumable runs · SQLite backend · sitemap discovery.

---

## What's new in v2

| #   | Feature                                                         | Flag / method                | Pattern             |
| --- | --------------------------------------------------------------- | ---------------------------- | ------------------- |
| 1   | **Resumable runs** — skip already-scraped URLs across crashes   | `resumable=True`             | Repository          |
| 2   | **Retry + exponential backoff** — auto-retry transient failures | `max_retries=3`              | Strategy            |
| 3   | **Change detection** — skip save if page content unchanged      | `skip_unchanged=True`        | Strategy            |
| 4   | **Pagination hook** — follow "next page" links automatically    | `collect_pages()` override   | Template Method     |
| 5   | **SQLite backend** — query results with SQL, not just files     | `use_sqlite=True`            | Repository          |
| 6   | **Sitemap discovery** — auto-read `sitemap.xml` / `robots.txt`  | `scrape_sitemap(url)`        | Utility             |
| 7   | **Domain rate limiter** — min gap between hits to same host     | `domain_rate_limit=5.0`      | Collaborator        |
| 8   | **Table extractor** — HTML tables → list of row dicts           | `use_parsing=True`           | Strategy (extended) |
| 9   | **Slow-page alerting** — flag pages above a time threshold      | `slow_page_threshold_sec=10` | Observer            |

---

## Table of contents

1. [Install](#1-install)
2. [Quick start](#2-quick-start)
3. [Architecture](#3-architecture)
4. [Design patterns](#4-design-patterns)
5. [All 9 new features](#5-all-9-new-features)
6. [Configuration reference](#6-configuration-reference)
7. [Output structure](#7-output-structure)
8. [CLI reference](#8-cli-reference)
9. [Running the tests](#9-running-the-tests)
10. [Extending the scraper](#10-extending-the-scraper)
11. [Best practices](#11-best-practices)
12. [Troubleshooting](#12-troubleshooting)
13. [File index](#13-file-index)

---

## 1. Install

```bash
pip install playwright httpx beautifulsoup4 nest_asyncio lxml
playwright install chromium
```

**Python 3.10+**

| Package                   | Role                                          |
| ------------------------- | --------------------------------------------- |
| `playwright`              | Async browser automation                      |
| `httpx`                   | Async HTTP — proxy fetching, sitemap fetching |
| `beautifulsoup4` + `lxml` | HTML parsing + sitemap XML parsing            |
| `nest_asyncio`            | `asyncio.run()` inside Jupyter notebooks      |

---

## 2. Quick start

### Jupyter / script

```python
from Iki_Scraper import ScraperFacade, ScraperConfig

# ── Minimal ───────────────────────────────────────────────
facade = ScraperFacade()
facade.scrape_one("https://example.com")

# ── With parsing + SQLite ─────────────────────────────────
cfg = ScraperConfig(use_parsing=True, use_sqlite=True)
ScraperFacade(cfg).scrape_many(["https://a.com", "https://b.com"])

# ── Resumable batch (safe to re-run after crash) ──────────
cfg = ScraperConfig(resumable=True, max_concurrency=5)
ScraperFacade(cfg).scrape_file("urls.txt")

# ── Discover sitemap + scrape all pages ───────────────────
ScraperFacade().scrape_sitemap("https://example.com")

# ── Check slow pages after run ────────────────────────────
facade = ScraperFacade(ScraperConfig(slow_page_threshold_sec=5.0))
facade.scrape_many(["https://a.com", "https://b.com"])
print(facade.slow_pages)   # [{"url": "...", "elapsed_s": 12.4}]
```

### CLI

```bash
# single URL, full features on
python Iki_Scraper.py --url https://example.com \
  --use-parsing --resumable --use-sqlite --slow-threshold 8

# batch file, domain rate-limited, retries enabled
python Iki_Scraper.py --file urls.txt \
  --concurrency 4 --domain-rate 3.0 --max-retries 3

# discover and scrape an entire site via sitemap
python Iki_Scraper.py --sitemap https://example.com --use-parsing

# skip pages whose content hasn't changed since last run
python Iki_Scraper.py --file urls.txt --skip-unchanged
```

---

## 3. Architecture

### Class map — single file, layered by dependency

```
Iki_Scraper.py
│
├── AppLogger                     Singleton — one logger, shared everywhere
├── ScraperConfig                 Dataclass — all knobs in one place
│
├── PATTERNS
│   ├── ParseStrategy (ABC)       Strategy interface
│   │   ├── RawHtmlStrategy       title only (default)
│   │   ├── BeautifulSoupStrategy title + meta + text + tables (#8)
│   │   └── ParseStrategyFactory  picks strategy from config
│   │
│   ├── RetryPolicy               Strategy — exponential backoff (#2)
│   ├── ChangeDetector            Strategy — SHA-256 content hashing (#3)
│   │
│   ├── ScrapeEvent               Value object
│   ├── ScrapeObserver (ABC)      Observer interface
│   ├── LoggingObserver           logs all events with icons
│   ├── SlowPageObserver          flags slow pages, records them (#9)
│   └── EventBus                  pub/sub — publish → all observers
│
│   ├── OutputRepository (ABC)    Repository interface
│   ├── LocalFileRepository       writes .html + _meta.json + summary
│   ├── SQLiteRepository          writes to SQLite db (#5)
│   └── CompositeRepository       writes to both simultaneously (#5)
│
│   ├── CheckpointStore           persists done URLs → .checkpoint.json (#1)
│   └── BrowserContextFactory     Factory — builds BrowserContext
│
├── INFRASTRUCTURE
│   ├── ProxyManager              fetches + round-robin rotates proxies
│   ├── DomainRateLimiter         per-domain asyncio.Lock gap (#7)
│   ├── HumanBehaviour            delay · mouse · gradual scroll
│   └── SitemapDiscovery          robots.txt + sitemap.xml parser (#6)
│
├── CORE
│   ├── BaseScraper (ABC)         Template Method — scrape_pipeline()
│   │   Hooks: before_navigate · after_navigate · after_extract · collect_pages (#4)
│   └── StandardScraper           concrete default (all hooks = no-ops)
│
├── ScraperOrchestrator           semaphore + gather + pagination queue
│
└── ScraperFacade                 Facade — 5 public methods, hides graph
    scrape_one · scrape_many · scrape_file · scrape_sitemap · add_observer
```

### Data flow — one URL end to end

```
ScraperFacade.scrape_one(url)
  │
  ▼
ScraperOrchestrator.run([url])
  │  asyncio.Semaphore — cap concurrent contexts
  ▼
BaseScraper.scrape_pipeline(url, browser)
  │
  ├─ CheckpointStore.is_done(url)?  → yes: return {status: "skipped"}   #1
  │
  ├─ ProxyManager.next_proxy()      → proxy dict | None
  ├─ random UA from ScraperConfig.user_agents
  ├─ DomainRateLimiter.acquire(url) → enforce per-domain gap             #7
  │
  ├─ BrowserContextFactory.create() → isolated BrowserContext
  │   └─ navigator.webdriver masked via add_init_script
  │
  ├─ hook: before_navigate()        → override for auth / cookies
  ├─ page.goto(url)
  ├─ hook: after_navigate()         → override for SPA / CAPTCHA checks
  │
  ├─ HumanBehaviour.mouse_wander()
  ├─ HumanBehaviour.gradual_scroll()  300 px / 1 s to bottom
  ├─ HumanBehaviour.random_delay()    1.5 – 4.0 s
  │
  ├─ page.content()                 → raw HTML
  ├─ hook: collect_pages()          → return extra URLs (pagination)      #4
  ├─ hook: after_extract()          → override for screenshots
  │
  ├─ ChangeDetector.has_changed()?  → no: return {status: "unchanged"}   #3
  │
  ├─ RetryPolicy.execute()  wraps all of the above on failure             #2
  │
  ├─ ParseStrategy.parse(html, url)
  │   ├─ RawHtmlStrategy    → {title}
  │   └─ BSStrategy         → {title, meta_desc, text, tables}           #8
  │
  ├─ OutputRepository.save_html()   → example_com.html
  ├─ OutputRepository.save_meta()   → example_com_meta.json
  │   └─ also writes to SQLite if use_sqlite=True                         #5
  │
  ├─ CheckpointStore.mark_done(url)                                       #1
  │
  ├─ EventBus.publish("url.success", elapsed_s=...)
  │   ├─ LoggingObserver    → log: "✓ Done …"
  │   └─ SlowPageObserver   → if elapsed_s > threshold: record            #9
  │
  └─ return result dict

ScraperOrchestrator
  ├─ enqueue extra_pages from collect_pages() results                     #4
  ├─ aggregate all results
  └─ OutputRepository.save_summary()  → scrape_summary.json
```

---

## 4. Design patterns

### Singleton — `AppLogger`

One logger instance, one format, shared by every class. `__new__` blocks direct instantiation. All classes call `AppLogger.get()`.

### Strategy — `ParseStrategy` · `RetryPolicy` · `ChangeDetector`

Three independent swappable algorithms. The scraper holds references to abstract interfaces and calls `.parse()`, `.execute()`, `.has_changed()` — it never knows the concrete class.

```
ParseStrategy     →  RawHtmlStrategy | BeautifulSoupStrategy | YourOwnStrategy
RetryPolicy       →  swap for NoRetry, LinearRetry, or CircuitBreaker
ChangeDetector    →  swap for RedisChangeDetector or DBChangeDetector
```

### Observer — `EventBus` + `ScrapeObserver`

The pipeline publishes named events. Any number of observers consume them independently. Observers are fault-isolated — one crash does not stop others.

```
Events: run.start · url.start · url.success · url.error · url.skip · url.slow · run.done
```

### Factory — `BrowserContextFactory`

Centralises all Playwright context wiring: UA, proxy, viewport, locale, timezone, webdriver mask. Callers call one method.

### Template Method — `BaseScraper`

`scrape_pipeline()` is the fixed skeleton. Four hooks are overridable entry points.

```
scrape_pipeline()      ← fixed, do not override
  before_navigate()    ← hook → auth, cookie injection
  navigate()           ← fixed
  after_navigate()     ← hook → SPA wait, CAPTCHA check
  interact()           ← fixed (mouse + scroll + delay)
  collect_pages()      ← hook → pagination URLs          ← NEW in v2
  extract()            ← fixed
  after_extract()      ← hook → screenshots, downloads
  persist()            ← fixed (Strategy + Repository)
```

### Repository — `OutputRepository`

Abstract persistence. Three concrete implementations, composable.

```
OutputRepository (ABC)
├── LocalFileRepository    →  disk files (default)
├── SQLiteRepository       →  SQLite db  (new v2)
└── CompositeRepository    →  both simultaneously (new v2)
```

### Facade — `ScraperFacade`

Five public methods, zero internal knowledge required.

```python
facade = ScraperFacade(cfg)
facade.scrape_one(url)
facade.scrape_many(urls)
facade.scrape_file(path)
facade.scrape_sitemap(base_url)   # new v2
facade.add_observer(observer)
facade.slow_pages                 # property, new v2
```

---

## 5. All 9 new features

### Feature 1 — Resumable runs

Saves completed URLs to `.checkpoint.json` in the output directory. Re-runs skip any URL already in the checkpoint. Safe across crashes, keyboard interrupts, and network failures.

```python
cfg = ScraperConfig(resumable=True)
ScraperFacade(cfg).scrape_file("10000_urls.txt")
# crash at URL 4832 → re-run → picks up at 4833
```

Reset a checkpoint manually:

```python
from Iki_Scraper import CheckpointStore
CheckpointStore("scraper_output").clear()
```

### Feature 2 — Retry + exponential backoff

Wraps the entire scrape pipeline in a retry loop. Wait time doubles each attempt: `base * 2^attempt`. 0 attempts = disabled.

```python
cfg = ScraperConfig(max_retries=3, retry_base_delay=2.0)
# attempt 1 fails → wait 2s → attempt 2 fails → wait 4s → attempt 3
```

### Feature 3 — Change detection

SHA-256 hashes each page's HTML and compares against the previous run. If the hash matches, skips saving and returns `status: "unchanged"`. Hashes persist in `.content_hashes.json`.

```python
cfg = ScraperConfig(skip_unchanged=True)
# first run: scrapes and saves all pages
# second run: skips pages with identical content
```

### Feature 4 — Pagination hook

Override `collect_pages()` in a `BaseScraper` subclass to return additional URLs found on the current page. The orchestrator automatically enqueues them for scraping.

```python
from Iki_Scraper import BaseScraper
from playwright.async_api import Page

class PaginatedScraper(BaseScraper):
    async def collect_pages(self, page: Page, url: str) -> list[str]:
        links = await page.query_selector_all("a.next-page")
        return [await l.get_attribute("href") for l in links if l]
```

### Feature 5 — SQLite backend

Stores every page in a local SQLite database alongside (or instead of) flat files. Query results with SQL. `CompositeRepository` writes to both.

```python
cfg = ScraperConfig(use_sqlite=True, sqlite_path="results.db")
```

Schema:

```sql
CREATE TABLE pages (
    url          TEXT PRIMARY KEY,
    filename     TEXT,
    timestamp    TEXT,
    http_status  INTEGER,
    size_bytes   INTEGER,
    meta_json    TEXT,
    html         TEXT
);
CREATE TABLE runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT,
    finished_at  TEXT,
    elapsed_s    REAL,
    total        INTEGER,
    success      INTEGER,
    error        INTEGER,
    summary_json TEXT
);
```

Query example:

```python
import sqlite3, json
con = sqlite3.connect("results.db")
rows = con.execute(
    "SELECT url, json_extract(meta_json,'$.title') FROM pages WHERE http_status=200"
).fetchall()
```

### Feature 6 — Sitemap discovery

Reads `robots.txt` to find the sitemap URL, then parses `sitemap.xml` (including nested sitemap index files) and returns a flat deduplicated list of all page URLs.

```python
# Via Facade — discover + scrape in one call
ScraperFacade(cfg).scrape_sitemap("https://example.com")

# Discover only, inspect before scraping
import asyncio
urls = asyncio.run(ScraperFacade().discover_sitemap("https://example.com"))
print(f"{len(urls)} URLs found")
```

### Feature 7 — Domain rate limiter

Enforces a minimum gap between requests to the same domain regardless of concurrency. Uses `asyncio.Lock` per domain so parallel coroutines queue correctly. Different domains are never blocked by each other.

```python
cfg = ScraperConfig(domain_rate_limit=3.0, max_concurrency=10)
# 10 parallel contexts, but same-domain requests spaced ≥ 3 s apart
```

### Feature 8 — Table extractor

When `use_parsing=True`, `BeautifulSoupStrategy` now extracts all HTML `<table>` elements and converts them to lists of row dicts, keyed by header text. Tables appear in `_meta.json` under the `"tables"` key.

```python
cfg = ScraperConfig(use_parsing=True)
```

Output in `_meta.json`:

```json
{
	"title": "...",
	"tables": [
		[
			{ "Name": "Alice", "Age": "30", "Role": "Engineer" },
			{ "Name": "Bob", "Age": "25", "Role": "Designer" }
		]
	]
}
```

### Feature 9 — Slow-page alerting

`SlowPageObserver` listens for `url.success` events. Any page whose `elapsed_s` exceeds `slow_page_threshold_sec` is recorded and logged as a warning. Access the list after the run via `facade.slow_pages`.

```python
cfg = ScraperConfig(slow_page_threshold_sec=8.0)
facade = ScraperFacade(cfg)
facade.scrape_many(urls)

for sp in facade.slow_pages:
    print(f"{sp['elapsed_s']:.1f}s  {sp['url']}")
```

The summary JSON also includes slow page data if you add `SlowPageObserver` to the orchestrator results.

---

## 6. Configuration reference

```python
@dataclass
class ScraperConfig:
    # Output
    output_dir: str = "scraper_output"
    save_html: bool = False
    use_parsing: bool = False

    # Concurrency
    max_concurrency: int = 3

    # Delays
    min_delay: float = 1.0
    max_delay: float = 3.0
    scroll_step_px: int = 500
    scroll_interval_sec: float = 1.0

    # Browser Settings
    headless: bool = True
    page_timeout_ms: int = 30_000
    viewport: dict = field(default_factory=lambda: {
                           "width": 1366, "height": 768})

    # Proxy Settings
    use_proxies: bool = False
    proxy_refresh_every: int = 30_000
    proxyscrape_timeout_ms: int = 5000

    # Resumable Runs
    resumable: bool = False

    # Retry + Backoff
    max_retries: int = 3
    retry_base_delay_sec: int = 3

    # Change Detection
    skip_unchanged: bool = False

    # SQLite Backend
    use_sqlite: bool = False
    sqlite_path: str = "scraper_data.db"

    # Domain Rate Limiter
    domain_rate_limit: float = 0.0

    # Slow-Page Alert
    slow_page_threshold_sec: float = 10.0
    user_agents: list[str]   = [...]     # 5 real-world UAs, rotated randomly
```

---

## 7. Output structure

```
scraper_output/
│
├── example_com.html                ← raw HTML (always)
├── example_com_meta.json           ← metadata per page
│
├── scrape_summary.json             ← run stats
│
├── .checkpoint.json                ← resumable run state  (hidden)
└── .content_hashes.json            ← change detection hashes  (hidden)

scraper.db                          ← SQLite db (if use_sqlite=True)
```

### `_meta.json` — all fields

```json
{
	"url": "https://example.com",
	"timestamp": "2025-01-01T12:00:00+00:00",
	"http_status": 200,
	"size_bytes": 12800,
	"user_agent": "Mozilla/5.0 ...",
	"proxy": null,

	"title": "Example Domain",

	"meta_description": "...",
	"text_preview": "First 5000 chars of clean body text ...",
	"tables": [[{ "Col A": "val1", "Col B": "val2" }]]
}
```

`meta_description`, `text_preview`, and `tables` only appear when `use_parsing=True`.

### `scrape_summary.json` — all fields

```json
{
  "started_at":   "2025-01-01T12:00:00+00:00",
  "finished_at":  "2025-01-01T12:00:42+00:00",
  "elapsed_s":    42.1,
  "total":        10,
  "success":      8,
  "error":        1,
  "skipped":      1,
  "unchanged":    0,
  "results":      [ ... ]
}
```

`skipped` = resumable checkpoint hits. `unchanged` = change-detection hits.

---

## 8. CLI reference

```
python Iki_Scraper.py [MODE] [OPTIONS]

Modes (pick one):
  --url URL               Single URL
  --urls URL [URL ...]    Multiple URLs
  --file PATH             .txt or .json URL list
  --sitemap BASE_URL      Discover sitemap + scrape all pages

Output:
  --output-dir DIR        Default: scraper_output
  --use-parsing           Enable BeautifulSoup + table extraction
  --use-sqlite            Also write to SQLite db
  --sqlite-path PATH      Default: scraper.db

Browser:
  --concurrency N         Default: 3
  --no-headless           Show browser window
  --use-proxies           Enable proxy rotation

Resilience:
  --resumable             Skip already-completed URLs
  --skip-unchanged        Skip save if content hash unchanged
  --max-retries N         Default: 3  (0 = disabled)
  --domain-rate SECS      Min seconds between same-domain requests
  --slow-threshold SECS   Flag pages slower than N seconds (default: 10)

Logging:
  --log-level LEVEL       DEBUG | INFO | WARNING | ERROR
```

---

## 9. Running the tests

```bash
# Unit tests — no browser, no network, < 2 s
python test_Iki_Scraper.py unit

# Pattern contract tests — no browser, < 1 s
python test_Iki_Scraper.py patterns

# Integration tests — real Chromium + public URLs, ~40 s
python test_Iki_Scraper.py integration

# All 67 tests
python test_Iki_Scraper.py
```

| Group       | Tests | Browser | Network |
| ----------- | ----- | ------- | ------- |
| unit        | 45    | ✗       | ✗       |
| patterns    | 9     | ✗       | ✗       |
| integration | 13    | ✓       | ✓       |

---

## 10. Extending the scraper

### Add Slack alerts on errors

```python
import requests
from Iki_Scraper import ScrapeObserver, ScrapeEvent, ScraperFacade

class SlackObserver(ScrapeObserver):
    def __init__(self, webhook: str):
        self._hook = webhook

    def on_event(self, event: ScrapeEvent) -> None:
        if event.name == "url.error":
            requests.post(self._hook, json={"text": event.payload["message"]})

facade = ScraperFacade()
facade.add_observer(SlackObserver("https://hooks.slack.com/..."))
```

### Add authenticated scraping

```python
from Iki_Scraper import BaseScraper, StandardScraper, ScraperConfig
from playwright.async_api import Page

class AuthScraper(BaseScraper):
    async def before_navigate(self, page: Page, url: str) -> None:
        await page.goto("https://site.com/login")
        await page.fill("#username", "you@email.com")
        await page.fill("#password", "secret")
        await page.click("[type=submit]")
        await page.wait_for_url("**/dashboard")

    async def after_navigate(self, page: Page, url: str) -> None:
        await page.wait_for_selector(".main-content", timeout=10_000)
```

### Add screenshot capture

```python
from pathlib import Path

class ScreenshotScraper(BaseScraper):
    async def after_navigate(self, page, url):
        self._page = page

    async def after_extract(self, page, html, url):
        fname = self._repo.filename_for(url)
        path  = Path(self._cfg.output_dir) / f"{fname}.png"
        await page.screenshot(path=str(path), full_page=True)
```

### Add custom pagination

```python
class PaginatedScraper(BaseScraper):
    async def collect_pages(self, page, url) -> list[str]:
        links = await page.query_selector_all("a.next-page")
        hrefs = [await l.get_attribute("href") for l in links]
        return [h for h in hrefs if h]
```

### Swap to S3 storage

```python
import boto3, json
from Iki_Scraper import OutputRepository

class S3Repository(OutputRepository):
    def __init__(self, bucket: str):
        self._s3     = boto3.client("s3")
        self._bucket = bucket

    def filename_for(self, url):
        import re
        return re.sub(r"[^\w\-]", "_", re.sub(r"https?://", "", url))[:120]

    def save_html(self, filename, html):
        self._s3.put_object(Bucket=self._bucket,
                            Key=f"{filename}.html", Body=html.encode())
        return f"s3://{self._bucket}/{filename}.html"

    def save_meta(self, filename, meta):
        self._s3.put_object(Bucket=self._bucket,
                            Key=f"{filename}_meta.json",
                            Body=json.dumps(meta).encode())
        return f"s3://{self._bucket}/{filename}_meta.json"

    def save_summary(self, summary):
        self._s3.put_object(Bucket=self._bucket,
                            Key="scrape_summary.json",
                            Body=json.dumps(summary).encode())
        return f"s3://{self._bucket}/scrape_summary.json"
```

### Add a custom LLM parser

```python
import openai, json
from Iki_Scraper import ParseStrategy

class LLMParseStrategy(ParseStrategy):
    def parse(self, html: str, url: str) -> dict:
        r = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user",
                       "content": f"Extract title, summary, entities as JSON:\n{html[:3000]}"}],
            response_format={"type": "json_object"},
        )
        return json.loads(r.choices[0].message.content)

facade = ScraperFacade(ScraperConfig(use_parsing=True))
facade._orch._scraper._parser = LLMParseStrategy()
```

---

## 11. Best practices

**Do**

- Start with `max_concurrency=2–3` on unfamiliar sites; increase only after confirming no rate-limiting.
- Always enable `resumable=True` for batches over 100 URLs — protects against crashes.
- Use `headless=False` when debugging — visible browser shows JS errors and redirects immediately.
- Run 3–5 URLs first as a smoke test before launching large batches.
- Use timestamped `output_dir` to keep separate run archives: `f"runs/{datetime.now():%Y%m%d_%H%M%S}"`.
- Combine `use_sqlite=True` with flat files — files are human-readable, SQLite is queryable.

**Don't**

- Don't set `min_delay` below `1.0 s` on sites you don't own.
- Don't rely on free proxies (ProxyScrape) for production — 30–60% are dead at any moment. Use them for exploration only.
- Don't set `max_concurrency > 10` without profiling. Each `BrowserContext` uses ~50–100 MB RAM.
- Don't ignore `error` in the summary. A rate above 20% means you're being blocked.
- Don't use `skip_unchanged` on sites with dynamic content (timestamps, ads) — every page will always look "changed".

**Free proxy reality check**

| Metric       | Typical range |
| ------------ | ------------- |
| Success rate | 30–60%        |
| Latency      | 2–10 s        |
| Lifespan     | Hours to days |

For production, swap `ProxyManager._fetch_pool()` to return hosts from Bright Data, Oxylabs, or SmartProxy.

---

## 12. Troubleshooting

| Symptom                              | Likely cause                 | Fix                                                                     |
| ------------------------------------ | ---------------------------- | ----------------------------------------------------------------------- |
| `TimeoutError` on many URLs          | Site slow or blocking        | Increase `page_timeout_ms`; enable proxies                              |
| Empty HTML                           | JS-heavy SPA                 | Change `wait_until` to `"networkidle"` in `page.goto()`                 |
| `ERR_PROXY_CONNECTION_FAILED`        | Dead free proxy              | Normal — they auto-rotate                                               |
| All pages show as `unchanged`        | Dynamic content (timestamps) | Disable `skip_unchanged` for that site                                  |
| Checkpoint not clearing between runs | `resumable=True` still set   | Call `CheckpointStore(output_dir).clear()` or delete `.checkpoint.json` |
| SQLite `OperationalError`            | DB file locked               | Only one `ScraperFacade` instance per db file                           |
| Sitemap returns 0 URLs               | Site uses non-standard path  | Pass the sitemap URL directly to `SitemapDiscovery().discover()`        |
| High RAM                             | Too many contexts            | Reduce `max_concurrency`                                                |
| CAPTCHA / 403                        | Fingerprint detected         | `headless=False`, reduce concurrency, better proxies                    |
| `RuntimeError: loop already running` | Jupyter without patch        | Import `Iki_Scraper` — triggers `nest_asyncio.apply()`                  |

---

## 13. File index

```
.
Iki-Scraper
├── src
│   ├── Iki_Scraper
│   │   ├── core
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py
│   │   │   └── standard_scraper.py
│   │   ├── infrastructure
│   │   │   ├── __init__.py
│   │   │   ├── context_factory.py
│   │   │   ├── domain_rate_limiter.py
│   │   │   ├── human_behavior.py
│   │   │   ├── proxy_manager.py
│   │   │   └── sitemap_discovery.py
│   │   ├── patterns
│   │   │   ├── __init__.py
│   │   │   ├── base_scraper.py
│   │   │   ├── change_detector.py
│   │   │   ├── checkpoint.py
│   │   │   ├── logger.py
│   │   │   ├── observer.py
│   │   │   ├── parse_strategy.py
│   │   │   ├── repository.py
│   │   │   └── retry_policy.py
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── config.py
│   │   └── facade.py
│   └── iki_scraper.egg-info
│       ├── dependency_links.txt
│       ├── entry_points.txt
│       ├── PKG-INFO
│       ├── SOURCES.txt
│       └── top_level.txt
├── tests
│   ├── test_integration.py
│   ├── test_patterns.py
│   └── test_unit.py
├── .gitignore
├── LICENSE.MD
├── pyproject.toml
├── README.MD
└── structure.py
```

---

_Unix Philosophy · Pareto Principle · Occam's Razor_
_Python 3.10+ · Playwright · asyncio · BeautifulSoup · httpx · SQLite_
