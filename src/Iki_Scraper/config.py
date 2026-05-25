
from dataclasses import dataclass, field


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

    # User-Agents
    user_agents: list[str] = field(default_factory=lambda: [
        # Chrome (most common)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",

        # Edge
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.3967.83",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.3967.83",

        # Firefox
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:151.0) Gecko/20100101 Firefox/151.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",

        # Safari
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",

        # Mobile (good for diversity)
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Mobile/15E148 Safari/604.1",
    ])
