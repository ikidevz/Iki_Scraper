"""
Concrete default scraper. All hooks are no-ops.
Subclass and override any hook to add auth, pagination, screenshots, etc.
"""

from ..patterns.base_scraper import BaseScraper


class StandardScraper(BaseScraper):
    pass
