# I Built a Production-Ready Web Scraper in Python — With 7 Design Patterns and 9 Features

_How I turned a quick scraping script into something I'm actually proud to put in a portfolio._

---

There's a certain point in every developer's journey where you look at a script you wrote six months ago and cringe.

Mine was a 200-line spaghetti scraper. It worked. Barely. One `if/else` tree that decided whether to parse HTML. A hardcoded output path. No retries. No way to resume if it crashed halfway through 10,000 URLs. And — the cherry on top — a function called `do_scrape_thing()`.

So I rebuilt it. Properly. From scratch.

What came out the other side is `Iki_Scraper` — an async Python web scraper built on Playwright, designed with 7 Gang-of-Four design patterns, 9 production features, and a test suite with 67 passing tests. This is the write-up of how I built it, what I learned, and why the architecture decisions matter.

---

## The Philosophy First

Before writing a single class I committed to three principles. These aren't buzzwords — they actively shaped every decision.

**Unix Philosophy.** Do one thing and do it well. Each class has exactly one reason to exist. The `ChangeDetector` only hashes content. The `DomainRateLimiter` only throttles. The `EventBus` only routes events. Nothing knows more than it needs to.

**Pareto Principle (80/20).** 80% of scraping problems come from 20% of failure modes: crashes mid-batch, transient network errors, getting blocked, and not knowing what's slow. I solved those first. The exotic edge cases can wait.

**Occam's Razor.** The simplest solution that works is the right one. No message queues, no microservices, no Redis — just Python, asyncio, and SQLite. Everything a working scraper needs, nothing it doesn't.

---

## The Stack

```
Python 3.10+
Playwright   — async browser automation
httpx        — async HTTP for proxy fetching and sitemaps
BeautifulSoup + lxml — HTML and XML parsing
SQLite       — built-in, zero-config database
nest_asyncio — makes asyncio.run() work in Jupyter
```

No bloated frameworks. No external services required to run. Clone, install, scrape.

---

## Why Playwright Over Requests or Scrapy?

A fair question. Here's my honest answer.

`requests` + `BeautifulSoup` is fine for static HTML — fast, lightweight, straightforward. But the modern web isn't mostly static. JavaScript-rendered content, infinite scroll, lazy-loaded images, login walls, cookie consent banners — these aren't edge cases anymore, they're the default.

Scrapy is powerful, but it's also a framework with opinions. It wants to own your project structure, your pipeline, your middlewares. I wanted to build my own architecture, not work inside someone else's.

Playwright gives you a real browser. Not a headless HTTP client pretending to be one — an actual Chromium instance that executes JavaScript, handles cookies, fires mouse events, and scrolls. That matters when you're scraping sites that actively try to detect bots.

---

## 7 Design Patterns — What They Are and Why I Used Them

Let me be direct: I didn't pick these patterns to impress anyone. I picked them because each one solved a specific problem I ran into.

### 1. Singleton — `AppLogger`

**The problem:** four different classes each calling `logging.basicConfig()` with different formats, producing garbage output.

**The solution:** one logger, created once, shared everywhere. `AppLogger.get()` initialises it on first call and returns the same instance on every subsequent call. `__new__` raises `TypeError` to prevent accidental direct instantiation.

```python
class AppLogger:
    _instance: Optional[logging.Logger] = None

    def __new__(cls):
        raise TypeError("Use AppLogger.get()")

    @classmethod
    def get(cls, level: str = "INFO") -> logging.Logger:
        if cls._instance is None:
            fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
            logging.basicConfig(format=fmt, datefmt="%Y-%m-%d %H:%M:%S", level=level)
            cls._instance = logging.getLogger("Iki_Scraper")
        return cls._instance
```

Boring? Yes. Effective? Absolutely.

---

### 2. Strategy — `ParseStrategy`

**The problem:** an `if cfg.use_parsing:` block buried inside the core scrape function. Parsing logic tangled with navigation logic.

**The solution:** extract the parsing algorithm behind an abstract interface. Two concrete implementations: `RawHtmlStrategy` (title only, default) and `BeautifulSoupStrategy` (title, meta description, body text, and HTML tables). Swap them at runtime without touching the pipeline.

```python
class ParseStrategy(abc.ABC):
    @abc.abstractmethod
    def parse(self, html: str, url: str) -> dict: ...

class RawHtmlStrategy(ParseStrategy):
    def parse(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title else ""
        return {"title": title}

class BeautifulSoupStrategy(ParseStrategy):
    def parse(self, html: str, url: str) -> dict:
        # title + meta + clean text + table extraction
        ...
```

I also used Strategy for retry logic (`RetryPolicy`) and change detection (`ChangeDetector`). Same interface pattern, completely swappable implementations.

---

### 3. Observer — `EventBus`

**The problem:** `log.info()` calls scattered through the scrape pipeline. Want to add a Slack alert? Edit the pipeline. Want Prometheus metrics? Edit it again.

**The solution:** the pipeline publishes named events. Observers consume them. Neither knows about the other.

```python
# Publisher — inside scrape_pipeline()
self._bus.publish("url.success", url=url, elapsed_s=elapsed)

# Consumer — anywhere, registered via facade.add_observer()
class SlackObserver(ScrapeObserver):
    def on_event(self, event: ScrapeEvent) -> None:
        if event.name == "url.error":
            requests.post(self._webhook, json={"text": event.payload["message"]})
```

Events published: `run.start`, `url.start`, `url.success`, `url.error`, `url.skip`, `run.done`. Add an observer that does anything — log to a file, post to Slack, increment a counter, send an email — without touching the scraper.

The `EventBus` also fault-isolates observers. One crashing observer logs a warning and moves on. The rest still run.

---

### 4. Factory — `BrowserContextFactory`

**The problem:** building a `BrowserContext` required six Playwright-specific kwargs — user agent, proxy, viewport, locale, timezone, and a webdriver masking init script — all inline in the scrape function.

**The solution:** one factory method. The scraper calls `ctx_factory.create(browser, ua, proxy)` and gets back a configured context. All the Playwright details are encapsulated.

This also makes testing dramatically easier. Mock the factory, swap in a fake context, and you can unit-test the entire pipeline without launching a browser.

---

### 5. Template Method — `BaseScraper`

This is the one I'm most proud of.

**The problem:** the scrape pipeline has a fixed sequence — navigate, interact, extract, persist — but individual steps need to be customisable for different use cases. Auth-protected sites need a login step. SPAs need a wait-for-selector step. Some pages need screenshots.

**The solution:** `scrape_pipeline()` is the fixed algorithm. Hook methods are empty by default and overridable in subclasses.

```
scrape_pipeline()          ← fixed skeleton, never override
  before_navigate()        ← hook: inject cookies, run login
  navigate()               ← fixed: page.goto()
  after_navigate()         ← hook: wait for SPA, check CAPTCHA
  interact()               ← fixed: mouse, scroll, delay
  collect_pages()          ← hook: return pagination URLs
  extract()                ← fixed: page.content()
  after_extract()          ← hook: screenshot, downloads
  persist()                ← fixed: parse + save
```

Adding auth to a scraper is now five lines:

```python
class AuthScraper(BaseScraper):
    async def before_navigate(self, page: Page, url: str) -> None:
        await page.goto("https://site.com/login")
        await page.fill("#username", "you@email.com")
        await page.fill("#password", "secret")
        await page.click("[type=submit]")
        await page.wait_for_url("**/dashboard")
```

Zero changes to the pipeline. Zero risk of breaking unrelated behaviour.

---

### 6. Repository — `OutputRepository`

**The problem:** `Path.write_text()` calls scattered through the pipeline. Switching to S3 storage means editing the core scraper.

**The solution:** abstract the persistence contract. The scraper calls `repo.save_html()` and `repo.save_meta()`. It doesn't know if that goes to disk, S3, or a database.

Three implementations ship: `LocalFileRepository` (disk), `SQLiteRepository` (database), and `CompositeRepository` (both simultaneously). The composite is my personal favourite — flat files are human-readable, SQLite is queryable. You get both for free.

---

### 7. Facade — `ScraperFacade`

**The problem:** the full object graph is eight collaborating classes. No caller should need to instantiate all of them.

**The solution:** one class, five methods.

```python
facade = ScraperFacade(cfg)
facade.scrape_one("https://example.com")
facade.scrape_many(["https://a.com", "https://b.com"])
facade.scrape_file("urls.txt")
facade.scrape_sitemap("https://example.com")
facade.add_observer(SlackObserver())
```

The entire object graph is assembled inside `_build_orchestrator()`. Callers never touch `ProxyManager`, `BrowserContextFactory`, `EventBus`, `CheckpointStore`, `DomainRateLimiter`, or `RetryPolicy` directly. They just get a clean API.

---

## 9 Production Features

The patterns gave me the architecture. These features made it actually useful.

### Feature 1 — Resumable Runs

The most painful scraping problem: you're halfway through 10,000 URLs, something crashes, and you start over from the beginning.

`CheckpointStore` solves this with a `.checkpoint.json` file that tracks completed URLs. Re-run the same command and it picks up exactly where it left off.

```python
cfg = ScraperConfig(resumable=True)
ScraperFacade(cfg).scrape_file("10000_urls.txt")
# crash at URL 7,432
# re-run → resumes at 7,433
```

### Feature 2 — Retry with Exponential Backoff

Most scraping errors are transient. `RetryPolicy` wraps the entire pipeline in a retry loop. Wait time doubles each attempt: `base * 2^attempt`. Three retries with a 2-second base gives waits of 2s, 4s, 8s — quiet enough to not hammer the server, persistent enough to survive momentary blocks.

### Feature 3 — Change Detection

For monitoring use cases — price tracking, news feeds, content changes — you don't want to save identical content on every run. `ChangeDetector` SHA-256 hashes each page and compares against the previous run. If nothing changed, skip it.

### Feature 4 — Pagination Hook

The Template Method `collect_pages()` hook returns additional URLs discovered on the current page. The orchestrator automatically enqueues and scrapes them. No manual pagination loops.

```python
class StoreScraper(BaseScraper):
    async def collect_pages(self, page: Page, url: str) -> list[str]:
        next_btn = await page.query_selector("a.next-page")
        href = await next_btn.get_attribute("href") if next_btn else None
        return [href] if href else []
```

### Feature 5 — SQLite Backend

Every result stored in a local SQLite database alongside the flat files. Query with SQL. Join tables. Export to CSV. No server, no setup, zero config.

```sql
SELECT url, json_extract(meta_json, '$.title'), http_status
FROM pages
WHERE http_status != 200
ORDER BY timestamp DESC;
```

### Feature 6 — Sitemap Discovery

Point it at a domain and it reads `robots.txt` to find the sitemap URL, then parses the full sitemap tree (including nested sitemap index files) and returns every page URL.

```python
ScraperFacade(cfg).scrape_sitemap("https://example.com")
# Finds, parses, and scrapes every URL in the sitemap automatically
```

### Feature 7 — Domain Rate Limiter

Global concurrency (`max_concurrency=10`) and per-domain throttling (`domain_rate_limit=3.0`) are orthogonal controls. You can run 10 parallel contexts across different domains while still spacing requests to the same domain 3 seconds apart. An `asyncio.Lock` per domain ensures correctness even under concurrency.

### Feature 8 — Table Extractor

When `use_parsing=True`, `BeautifulSoupStrategy` now converts every `<table>` element to a list of row dicts, keyed by header text. Financial data, sports stats, government tables — all extracted cleanly.

```json
"tables": [
  [
    {"Company": "Acme Corp", "Revenue": "$4.2B", "Growth": "12%"},
    {"Company": "Globex",    "Revenue": "$2.1B", "Growth": "8%"}
  ]
]
```

### Feature 9 — Slow-Page Alerting

`SlowPageObserver` listens for `url.success` events and flags any page that took longer than the configured threshold. Access the list after the run:

```python
facade = ScraperFacade(ScraperConfig(slow_page_threshold_s=8.0))
facade.scrape_many(urls)
print(facade.slow_pages)
# [{"url": "https://slow-cdn-site.com/page", "elapsed_s": 23.4}]
```

---

## Human-Like Behaviour

None of the features matter if you get blocked immediately. Three layers of human simulation are baked in:

**Rotating User-Agents.** Five real-world browser UAs rotated randomly per request. Not a static string, not a fake — actual Chrome, Safari, Firefox, and Edge identifiers from recent versions.

**Mouse movement.** Before scrolling, the scraper moves the mouse in 4–8 random arcs across the viewport. JavaScript fingerprinters check for mouse events — this satisfies them.

**Gradual scroll.** `HumanBehaviour.gradual_scroll()` increments `window.scrollTo` by 300px every second, all the way to the bottom of the page. This fires lazy-load triggers and infinite-scroll listeners naturally. A real person reading the page — not a bot that jumps straight to the bottom.

Combined with `navigator.webdriver` masking via `add_init_script`, isolated `BrowserContext` per URL (separate cookies, storage, and headers per request), and random delays between requests, the default configuration is reasonably hard to fingerprint.

---

## The Architecture in One Diagram

```
ScraperFacade               ← the only class you need to touch
  │
  ├── EventBus              ← publish events → all observers react
  │   ├── LoggingObserver
  │   └── SlowPageObserver
  │
  ├── ScraperOrchestrator   ← semaphore + asyncio.gather + pagination queue
  │   └── BaseScraper       ← Template Method: fixed pipeline + 4 hooks
  │       ├── BrowserContextFactory
  │       ├── ProxyManager
  │       ├── DomainRateLimiter
  │       ├── ParseStrategy  (RawHtml | BeautifulSoup)
  │       ├── RetryPolicy
  │       ├── ChangeDetector
  │       └── CheckpointStore
  │
  └── OutputRepository
      ├── LocalFileRepository
      ├── SQLiteRepository
      └── CompositeRepository
```

Dependency flows inward. Nothing in the inner layers knows about the outer layers. No circular imports. Completely testable at each level independently.

---

## The Test Suite

67 tests across three groups:

**Unit tests (45)** — no browser, no network, runs in under 2 seconds. Every class tested in pure isolation. The `BaseScraper` pipeline test uses `AsyncMock` to fully mock Playwright without launching a browser.

**Pattern contract tests (10)** — validates the design pattern guarantees: Liskov Substitution (any `ParseStrategy` is drop-in replaceable), Singleton identity (10 calls return the same object), Observer crash isolation (one crashing observer doesn't stop others), Template Method hook ordering (before < after < extract).

**Integration tests (13)** — real Chromium, real public URLs. Tests every feature end-to-end including resumable runs, change detection, SQLite writes, slow-page alerting, and domain rate limiting.

The test runner is custom — no pytest, no pytest-asyncio, no configuration files. Just `python tests/test_unit.py` and it works.

---

## The CLI

```
python main.py --url https://example.com
python main.py --urls https://a.com https://b.com --use-parsing
python main.py --file urls.txt --concurrency 5 --resumable --use-sqlite
python main.py --sitemap https://example.com --use-parsing --slow-threshold 8
```

Arguments are grouped into four sections — `output`, `browser`, `resilience`, `observability` — so `--help` is actually readable. `--url` and `--urls` are mutually exclusive at the argparse level. You cannot pass both. Returns exit code 0 on full success, 1 if any errors — composable in CI pipelines and shell scripts.

---

## What I Learned Building This

**Design patterns are problem solutions, not vocabulary.** I didn't start with "I'll use Strategy here." I started with "this `if/else` block is a maintenance nightmare" and reached for the tool that solved it. Every pattern in this codebase earned its place by solving a specific, felt problem.

**The 80/20 rule is brutally clarifying.** When I listed everything a production scraper could do, the list was overwhelming. When I asked "what failures actually kill a scraping run?" the answer was clear: crashes mid-batch, transient errors, and getting blocked. I built those solutions first and they covered most of the value. The remaining 20% of features took much longer to build and mattered much less.

**Async Python is genuinely pleasant once it clicks.** `asyncio.gather()` with a `Semaphore` gives you clean, readable concurrency without threads. The hardest part is remembering to `await ctx.close()` in the `finally` block — leaked browser contexts accumulate silently and exhaust memory.

**Mocking Playwright for unit tests is worth the setup cost.** The `AsyncMock` / `MagicMock` Playwright mock pattern took a couple of hours to get right. But it means 45 of the 67 tests run in under 2 seconds with zero browser dependency. That makes the test suite something I actually run before every commit.

**A clean public API changes how you think about a codebase.** Once I committed to "callers only see `ScraperFacade`," every internal class became easier to design. It doesn't need a friendly interface — it just needs to do its job. The Facade absorbs all the wiring complexity so the internal classes can stay focused.

---

## Final Thoughts

This is the scraper I wish I'd had a year ago. Not because it's perfect — there's plenty I'd still improve — but because it's built on a foundation that makes improvement easy. Adding a new feature means picking a pattern, implementing one class, and wiring it in one place. Swapping storage backends is one class and two injections. Adding a Slack alert is one observer and one `facade.add_observer()` call.

That's what good architecture buys you. Not a perfect system on day one. A system that stays manageable as it grows.

The full project — scraper, tests, docs, and CLI — is in my repository. If you're building something similar or want to talk about the architecture decisions, I'd love to hear from you.

---
