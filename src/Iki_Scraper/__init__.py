"""
Iki-Scraper
Advanced asynchronous web scraping framework with proxy rotation,
human behavior simulation, and robust architecture.
"""

__version__ = "0.1.0"
__author__ = "IkiDevz"

# Core
from .core import (
    ScraperOrchestrator,
    StandardScraper,
    BrowserSession,
)

# Infrastructure
from .infrastructure import (
    ProxyManager,
    BrowserContextFactory,
    DomainRateLimiter,
    HumanBehaviour,
    SitemapDiscovery,
    UrlLoader,
)

# Patterns
from .patterns import (
    BaseScraper,
    ChangeDetector,
    CheckpointStore,
    AppLogger,
    ScrapeEvent,
    ScrapeObserver,
    LoggingObserver,
    SlowPageObserver,
    EventBus,
    ParseStrategy,
    RawHtmlStrategy,
    BeautifulSoupStrategy,
    ParseStrategyFactory,
    OutputRepository,
    LocalFileRepository,
    SQLiteRepository,
    CompositeRepository,
    RetryPolicy
)

# Root package modules
from .config import ScraperConfig
from .facade import ScraperFacade


__all__ = [

    # Core
    "ScraperOrchestrator",
    "StandardScraper",
    "BrowserSession",

    # Infrastructure
    "ProxyManager",
    "BrowserContextFactory",
    "DomainRateLimiter",
    "HumanBehaviour",
    "SitemapDiscovery",
    "UrlLoader",

    # Patterns
    "AppLogger",
    "BaseScraper",
    "ChangeDetector",
    "CheckpointStore",
    "ScrapeEvent",
    "ScrapeObserver",
    "LoggingObserver",
    "SlowPageObserver",
    "EventBus",
    "ParseStrategy",
    "RawHtmlStrategy",
    "BeautifulSoupStrategy",
    "ParseStrategyFactory",
    "OutputRepository",
    "LocalFileRepository",
    "SQLiteRepository",
    "CompositeRepository",
    "RetryPolicy",

    # Config & Facade
    "ScraperConfig",
    "ScraperFacade",
]
