# Iki-Scraper

> Advanced async web scraping framework built on Playwright — with a clean, verb-first public API.

```python
from Iki_Scraper.facade import ScraperFacade

s = ScraperFacade()

# Scrape a page
s.fetch("https://example.com")

# Grab a specific element by CSS selector
title = s.select("https://example.com", "h1")
price = s.select("https://books.toscrape.com", "p.price_color")

# Pull every matching element
links = s.select_all("https://example.com", "a", attribute="href")

# Extract a <table> as structured rows
rows = s.select_table("https://en.wikipedia.org/wiki/Python_(programming_language)", "table.wikitable")

# Structured metadata extraction
data = s.parse("https://example.com")
# → {"title": "...", "meta_description": "...", "text_preview": "...", "tables": [...]}
```

---

## Installation

```bash
git clone https://github.com/yourname/Iki-Scraper
cd Iki-Scraper
pip install -e .
playwright install chromium
```

---

## Table of Contents

- [Quick examples](#quick-examples)
- [API reference](#api-reference)
  - [FETCH — browser scraping](#fetch--browser-scraping)
  - [SELECT — live CSS queries](#select--live-css-queries)
  - [PARSE — structured extraction](#parse--structured-extraction)
  - [DETECT — change detection](#detect--change-detection)
  - [RESUME — resumable runs](#resume--resumable-runs)
  - [DISCOVER — sitemap](#discover--sitemap)
  - [OBSERVE — event hooks](#observe--event-hooks)
  - [STORE — SQLite](#store--sqlite)
  - [CONFIG — inspection](#config--inspection)
- [ScraperConfig reference](#scraperconfig-reference)
- [Architecture](#architecture)

---

## Quick examples

### Scrape one page

```python
from Iki_Scraper.facade import ScraperFacade

s = ScraperFacade()
summary = s.fetch("https://example.com")

print(summary["success"])   # 1
print(summary["elapsed_s"]) # 2.3
print(summary["results"][0]["http_status"])  # 200
```

### Grab a CSS selector — the direct scrape you want

```python
# inner text of first matching element
h1    = s.select("https://example.com",          "h1")
price = s.select("https://books.toscrape.com",   "p.price_color")
desc  = s.select("https://books.toscrape.com",   "p.description_text")

# grab an attribute instead of text
href  = s.select("https://example.com", "a",   attribute="href")
src   = s.select("https://example.com", "img", attribute="src")
cls   = s.select("https://books.toscrape.com", "p.star-rating", attribute="class")

# returns None if selector not found — never raises
x = s.select("https://example.com", "div.ghost")  # → None
```

### Grab every matching element

```python
# all paragraph texts
paras  = s.select_all("https://example.com", "p")

# all hrefs
links  = s.select_all("https://example.com", "a", attribute="href")

# first 5 product titles
titles = s.select_all(
    "https://books.toscrape.com",
    "article.product_pod h3 a",
    attribute="title",
    limit=5,
)
```

### Query multiple selectors in one browser session

```python
data = s.select_many("https://books.toscrape.com", {
    "page_title":  "title",
    "first_price": "p.price_color",
    "rating":      {"selector": "p.star-rating",  "attribute": "class"},
    "all_links":   {"selector": "article h3 a",   "attribute": "href",  "all": True},
    "all_prices":  {"selector": "p.price_color",  "all": True},
})
# data["all_links"]  → ["catalogue/...", "catalogue/...", ...]
# data["all_prices"] → ["£51.77", "£53.74", ...]
```

### Extract a `<table>` as structured data

```python
rows = s.select_table(
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "table.wikitable",
)
# → [{"Release": "3.12", "Date": "2023-10-02", ...}, ...]

# second table on a page
rows2 = s.select_table("https://example.com/stats", "table", index=1)
```

### Scrape many URLs concurrently

```python
from Iki_Scraper.config import ScraperConfig

s = ScraperFacade(ScraperConfig(max_concurrency=5))
summary = s.fetch_many([
    "https://example.com",
    "https://httpbin.org/html",
    "https://books.toscrape.com",
])
```

### Load URLs from a file

```python
# urls.txt — one per line, # comments ignored
summary = s.fetch_file("urls.txt")

# urls.json — ["https://...", "https://..."]
summary = s.fetch_file("urls.json")
```

### Structured metadata extraction

```python
# parse returns a dict with title, meta_description, text_preview, tables
data = s.parse("https://example.com")
print(data["title"])
print(data["meta_description"])
print(data["text_preview"][:200])
if "tables" in data:
    print(data["tables"][0])  # list of {"col": "val"} dicts

# parse multiple pages concurrently
results = s.parse_many(["https://example.com", "https://httpbin.org/html"])
```

---

## API reference

### FETCH — browser scraping

| Method                    | Description                                         |
| ------------------------- | --------------------------------------------------- |
| `fetch(url)`              | Scrape a single URL. Returns run-summary dict.      |
| `fetch_many(urls)`        | Scrape a list of URLs concurrently.                 |
| `fetch_file(path)`        | Load URLs from `.txt` or `.json` file, then scrape. |
| `fetch_sitemap(base_url)` | Discover sitemap, then scrape every URL in it.      |

**Run-summary dict shape:**

```python
{
    "total":      3,
    "success":    2,
    "error":      1,
    "skipped":    0,
    "unchanged":  0,
    "elapsed_s":  4.7,
    "started_at": "2024-01-01T00:00:00+00:00",
    "finished_at":"2024-01-01T00:00:05+00:00",
    "results": [
        {
            "url":         "https://example.com",
            "status":      "success",       # success | error | skipped | unchanged
            "http_status": 200,
            "size_bytes":  12480,
            "elapsed_s":   1.8,
            "timestamp":   "...",
            "html_file":   "/out/example_com.html",   # if save_html=True
            "meta_file":   "/out/example_com_meta.json",
            "extra_pages": [],
            "error":       None,
        },
        ...
    ]
}
```

---

### SELECT — live CSS queries

These methods open the page in a real Chromium browser and query the live DOM — so JavaScript-rendered content works too.

| Method                                                             | Description                                        |
| ------------------------------------------------------------------ | -------------------------------------------------- |
| `select(url, selector, attribute=None, wait=True)`                 | First matching element → `str` or `None`           |
| `select_all(url, selector, attribute=None, wait=True, limit=None)` | All matching elements → `list[str]`                |
| `select_many(url, selectors: dict)`                                | Multiple selectors in one browser session → `dict` |
| `select_table(url, selector="table", index=0)`                     | Extract `<table>` → `list[dict]`                   |

#### `select()` — single element

```python
# text content (default)
s.select("https://example.com", "h1")
s.select("https://books.toscrape.com", "p.price_color")
s.select("https://books.toscrape.com", "article:first-child h3 a", attribute="title")

# attribute value
s.select("https://example.com", "a",   attribute="href")
s.select("https://example.com", "img", attribute="src")

# XPath also works
s.select("https://example.com", "xpath=//h1[1]")

# Returns None if not found — never raises
s.select("https://example.com", ".ghost")  # → None
```

#### `select_all()` — multiple elements

```python
# all texts
s.select_all("https://example.com", "p")
s.select_all("https://example.com", "li")

# all attribute values
s.select_all("https://example.com", "a",   attribute="href")
s.select_all("https://example.com", "img", attribute="src")

# limit results
s.select_all("https://books.toscrape.com", "p.price_color", limit=5)

# returns [] if nothing matches
s.select_all("https://example.com", ".ghost")  # → []
```

#### `select_many()` — multi-field in one session

```python
data = s.select_many("https://books.toscrape.com", {
    # string shorthand — first match, inner text
    "heading": "h1",

    # full dict — first match, attribute
    "rating": {"selector": "p.star-rating", "attribute": "class"},

    # full dict — all matches, inner text
    "all_prices": {"selector": "p.price_color", "all": True},

    # full dict — all matches, attribute
    "all_hrefs": {"selector": "a", "attribute": "href", "all": True},
})
```

`selectors` spec per key:

| Value type                                             | Meaning                      |
| ------------------------------------------------------ | ---------------------------- |
| `"css selector"`                                       | First match, inner text      |
| `{"selector": "...", "attribute": "..."}`              | First match, attribute value |
| `{"selector": "...", "all": True}`                     | All matches, inner text      |
| `{"selector": "...", "attribute": "...", "all": True}` | All matches, attribute       |

#### `select_table()` — table extraction

```python
# default: first <table> on the page
rows = s.select_table("https://example.com/data", "table")

# specific table selector
rows = s.select_table(
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "table.wikitable",
)

# second matched table
rows = s.select_table("https://example.com", "table", index=1)

# → [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}]
```

---

### PARSE — structured extraction

Uses BeautifulSoup to extract structured metadata. Always forces `use_parsing=True` internally regardless of config.

```python
data = s.parse("https://example.com")
# {
#   "title":            "Example Domain",
#   "meta_description": "...",
#   "text_preview":     "This domain is for use in illustrative...",  # ≤2000 chars
#   "tables":           [...]   # only present when page has <table>
# }

# multiple pages concurrently
results = s.parse_many(["https://example.com", "https://httpbin.org/html"])
# → [{"title": "...", ...}, {"title": "...", ...}]
```

---

### DETECT — change detection

Stores a SHA-256 hash of each page's HTML after the first visit. Subsequent calls with the same content return `status="unchanged"` without re-saving.

```python
# first run — saves everything
s1 = s.detect_changes(["https://example.com", "https://httpbin.org/html"])
print(s1["success"])    # 2
print(s1["unchanged"])  # 0

# second run — same content, nothing re-saved
s2 = s.detect_changes(["https://example.com", "https://httpbin.org/html"])
print(s2["success"])    # 0
print(s2["unchanged"])  # 2

# wipe hashes to force a full re-save next time
s.reset_hashes()
```

---

### RESUME — resumable runs

Persists completed URLs to `.checkpoint.json`. Re-running the same job skips already-done URLs instantly.

```python
urls = ["https://a.com", "https://b.com", "https://c.com"]

# Run 1 — scrapes all 3
r1 = s.resume(urls)
print(r1["success"])  # 3
print(r1["skipped"])  # 0

# Run 2 — all already done
r2 = s.resume(urls)
print(r2["success"])  # 0
print(r2["skipped"])  # 3

# Inspect checkpoint without modifying it
status = s.checkpoint_status()
# {"done_count": 3, "done_urls": [...], "file": "/path/.checkpoint.json"}

# Erase checkpoint to start fresh
s.clear_checkpoint()
```

---

### DISCOVER — sitemap

Returns a flat list of URLs from the sitemap — without launching a browser or scraping anything.

```python
urls = s.discover("https://books.toscrape.com")
# ["https://books.toscrape.com/catalogue/...", ...]

print(f"Found {len(urls)} URLs")

# Then scrape a subset
summary = s.fetch_many(urls[:10])
```

Discovery order: reads `robots.txt` for a `Sitemap:` directive → falls back to `/sitemap.xml`. Handles sitemap index files recursively.

---

### OBSERVE — event hooks

```python
from Iki_Scraper.patterns.observer import ScrapeObserver, ScrapeEvent

class MyObserver(ScrapeObserver):
    def on_event(self, event: ScrapeEvent) -> None:
        print(f"[{event.name}] {event.payload.get('message', '')}")

s.observe(MyObserver())
s.fetch("https://example.com")
# [run.start]  Starting run — 1 URL(s)
# [url.start]  Visiting https://example.com
# [url.success] Done https://example.com (12480 bytes, HTTP 200, 1.8s)
# [run.done]   Run complete — ✓ 1  ✗ 0  ↷ 0  (1.8s)
```

**Standard event names:**

| Event         | When fired                            |
| ------------- | ------------------------------------- |
| `run.start`   | Before the run begins                 |
| `run.done`    | After all URLs finish                 |
| `url.start`   | Browser is navigating to a URL        |
| `url.success` | Page scraped and saved successfully   |
| `url.error`   | Page failed after all retries         |
| `url.skip`    | URL skipped (checkpoint or unchanged) |

```python
# Inspect slow pages after a run
s.fetch_many(urls)
slow = s.get_slow_pages()
# [{"url": "https://slow.com", "elapsed_s": 14.2}, ...]
```

---

### STORE — SQLite

Enable the SQLite backend in config, then query it directly.

```python
from Iki_Scraper.config import ScraperConfig

s = ScraperFacade(ScraperConfig(
    use_sqlite=True,
    sqlite_path="scraper_data.db",
))

s.fetch_many(["https://example.com", "https://httpbin.org/html"])

# Raw SQL SELECT — returns list of dicts
rows = s.query_db("SELECT url, http_status FROM pages WHERE http_status = 200")

# All pages in the DB
pages = s.list_saved()
# [{"url": ..., "http_status": 200, "size_bytes": ..., "timestamp": ...}, ...]

# All run records
runs = s.get_run_history()
# [{"id": 1, "started_at": ..., "elapsed_s": 2.3, "total": 2, "success": 2}, ...]

# Export pages table to JSON
path = s.export_json("export.json")
```

**SQLite schema:**

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

---

### CONFIG — inspection

```python
info = s.describe()
# {
#   "config": {
#     "output_dir": "scraper_output", "max_concurrency": 3,
#     "headless": True, "min_delay": 1.0, "max_delay": 3.0,
#     "viewport": {"width": 1366, "height": 768},
#     "user_agent_count": 12, ...
#   },
#   "features": {
#     "resumable": False, "skip_unchanged": False,
#     "use_parsing": False, "save_html": False,
#     "use_sqlite": False, "sqlite_path": None,
#     "use_proxies": False, "domain_rate_limit_s": 0.0,
#     "max_retries": 3, "slow_page_threshold_s": 10.0, ...
#   },
#   "state": {
#     "slow_pages_recorded": 0,
#     "checkpoint_file": "/abs/path/.checkpoint.json",
#     "hash_file":       "/abs/path/.content_hashes.json",
#   }
# }
```

---

## ScraperConfig reference

```python
from Iki_Scraper.config import ScraperConfig

cfg = ScraperConfig(
    # Output
    output_dir          = "scraper_output",  # where files are written
    save_html           = False,             # save raw .html files to disk
    use_parsing         = False,             # enable BeautifulSoup extraction

    # Concurrency
    max_concurrency     = 3,                 # simultaneous browser tabs

    # Delays (human simulation)
    min_delay           = 1.0,              # seconds — min random delay per page
    max_delay           = 3.0,              # seconds — max random delay per page
    scroll_step_px      = 500,              # pixels per gradual scroll step
    scroll_interval_sec = 1.0,              # pause between scroll steps

    # Browser
    headless            = True,             # False = visible browser window
    page_timeout_ms     = 30_000,           # ms before navigation times out
    viewport            = {"width": 1366, "height": 768},

    # Proxy
    use_proxies         = False,            # enable proxy rotation
    proxy_refresh_every = 30_000,           # requests between proxy pool refresh

    # Resumable runs
    resumable           = False,            # enable checkpoint store

    # Retry / backoff
    max_retries         = 3,               # retries per URL (0 = no retry)
    retry_base_delay_sec= 3,               # base for exponential backoff

    # Change detection
    skip_unchanged      = False,           # skip re-saving if content hash matches

    # SQLite backend
    use_sqlite          = False,           # enable SQLite output
    sqlite_path         = "scraper_data.db",

    # Domain rate limiter
    domain_rate_limit   = 0.0,            # min seconds between requests to same domain (0 = off)

    # Slow-page alert threshold
    slow_page_threshold_sec = 10.0,       # pages above this appear in get_slow_pages()

    # User-agents (12 built-in Chrome/Firefox/Safari/Edge/Mobile)
    user_agents         = [...],          # override with your own list
)
```

---

## Architecture

```
ScraperFacade          ← public API (this file)
    │
    ├── ScraperOrchestrator    ← drives asyncio concurrency + pagination
    │       └── BaseScraper   ← Template Method: fixed pipeline + 4 hooks
    │               └── StandardScraper  ← default (no-op hooks)
    │
    ├── EventBus               ← pub/sub for run/url events
    │       ├── LoggingObserver
    │       └── SlowPageObserver
    │
    ├── OutputRepository       ← pluggable persistence
    │       ├── LocalFileRepository   (.html + _meta.json)
    │       ├── SQLiteRepository      (pages + runs tables)
    │       └── CompositeRepository   (both simultaneously)
    │
    ├── ParseStrategy          ← Strategy pattern for HTML extraction
    │       ├── RawHtmlStrategy        (title only)
    │       └── BeautifulSoupStrategy  (title, meta, text, tables)
    │
    ├── CheckpointStore        ← .checkpoint.json (resumable)
    ├── ChangeDetector         ← .content_hashes.json (skip-unchanged)
    ├── RetryPolicy            ← exponential-backoff async wrapper
    ├── DomainRateLimiter      ← per-domain asyncio.Lock + gap
    ├── ProxyManager           ← multi-source pool + round-robin rotation
    ├── BrowserContextFactory  ← Playwright context + UA + proxy + fingerprint
    ├── HumanBehaviour         ← random delay, mouse wander, gradual scroll
    └── SitemapDiscovery       ← robots.txt → sitemap.xml → recursive parse
```

### Extending — hook into the scraper pipeline

```python
from Iki_Scraper.core import StandardScraper

class AuthScraper(StandardScraper):
    async def before_navigate(self, page, url):
        # inject cookies, localStorage, login
        await page.set_extra_http_headers({"Authorization": "Bearer ..."})

    async def after_navigate(self, page, url):
        # wait for SPA to hydrate
        await page.wait_for_selector("#app-loaded")

    async def after_extract(self, page, html, url):
        # take a screenshot, download assets
        await page.screenshot(path=f"shot_{hash(url)}.png")

    async def collect_pages(self, page, url):
        # return pagination links
        els = await page.query_selector_all("a.next-page")
        return [await el.get_attribute("href") for el in els]
```

---

## Running the examples

```bash
# Install
pip install -e /path/to/Iki-Scraper
playwright install chromium

# Full showcase (all sections)
python examples.py

# Sections A–G run without a browser (pure-Python unit-level)
# Sections H–X spin up Chromium and hit real URLs
```

---

## License

MIT — see `LICENSE`
