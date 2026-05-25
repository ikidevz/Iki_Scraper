"""
Fetches and parses sitemap.xml (and sitemap index files).
Falls back to robots.txt to locate the sitemap URL automatically.
Returns a flat deduplicated list of page URLs.
"""

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import Optional
from ..patterns.logger import AppLogger

log = AppLogger.get()


class SitemapDiscovery:
    async def discover(self, base_url: str) -> list[str]:
        """Entry point: returns all URLs found in the sitemap."""
        sitemap_url = await self._find_sitemap_url(base_url)
        if not sitemap_url:
            log.warning("No sitemap found for %s", base_url)
            return []
        return await self._parse_sitemap(sitemap_url)

    async def _find_sitemap_url(self, base_url: str) -> Optional[str]:
        """Check robots.txt first, then fall back to /sitemap.xml."""
        robots_url = urljoin(base_url, "/robots.txt")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(robots_url)
                for line in r.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        # Fallback: standard location
        return urljoin(base_url, "/sitemap.xml")

    async def _fetch_xml(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.text
        except Exception as exc:
            log.warning("Sitemap fetch failed %s: %s", url, exc)
        return None

    async def _parse_sitemap(self, url: str) -> list[str]:
        """Handles both sitemap index (nested) and regular sitemaps."""
        xml = await self._fetch_xml(url)
        if not xml:
            return []

        soup = BeautifulSoup(xml, "xml")
        urls: list[str] = []

        for loc in soup.find_all("sitemap"):
            child_url = loc.find("loc")
            if child_url:
                urls.extend(await self._parse_sitemap(child_url.text.strip()))

        for loc in soup.find_all("url"):
            l = loc.find("loc")
            if l:
                urls.append(l.text.strip())

        log.info("Sitemap %s → %d URLs", url, len(urls))
        return list(dict.fromkeys(urls))
