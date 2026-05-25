from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from ..config import ScraperConfig


class ParseStrategy(ABC):
    """Abstract: how to extract structured data from raw HTML."""

    @abstractmethod
    def parse(self, html: str, url: str) -> dict: ...


class RawHtmlStrategy(ParseStrategy):
    """Minimal — title tag only. Default mode."""

    def parse(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        title = (
            soup.title.string.strip()
            if soup.title and soup.title.string else ""
        )
        return {"title": title}


class BeautifulSoupStrategy(ParseStrategy):
    """
    Rich extraction — title, meta description, clean text preview.
    Feature #8: also extracts HTML tables → list of dicts per table.
    """

    MAX_TEXT_CHARS = 5_000
    NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside"]

    def parse(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")

        title = (
            soup.title.string.strip()
            if soup.title and soup.title.string else ""
        )

        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = str(meta_tag["content"]).strip()

        # Feature #8 — Table extractor: pull tables BEFORE removing noise tags
        tables = self._extract_tables(soup)

        for tag in soup(self.NOISE_TAGS):
            tag.decompose()

        text = " ".join(soup.get_text(separator=" ").split())
        text = text[: self.MAX_TEXT_CHARS]

        result = {
            "title":           title,
            "meta_description": meta_desc,
            "text_preview":    text,
        }
        if tables:
            result["tables"] = tables
        return result

    @staticmethod
    def _extract_tables(soup: BeautifulSoup) -> list[list[dict]]:
        """
        Convert every <table> to a list of row-dicts keyed by header text.
        Returns a list of tables; each table is a list of row dicts.
        """
        all_tables: list[list[dict]] = []
        for table in soup.find_all("table"):
            headers: list[str] = []
            rows: list[dict] = []
            for i, tr in enumerate(table.find_all("tr")):
                cells = [td.get_text(strip=True)
                         for td in tr.find_all(["th", "td"])]
                if not cells:
                    continue
                if i == 0 or tr.find("th"):
                    headers = cells
                else:
                    if headers:
                        # zip stops at shortest — handles ragged tables cleanly
                        rows.append(dict(zip(headers, cells)))
                    else:
                        rows.append({str(j): v for j, v in enumerate(cells)})
            if rows:
                all_tables.append(rows)
        return all_tables


class ParseStrategyFactory:
    """Picks the right strategy from config. Keeps selection logic DRY."""

    @staticmethod
    def create(cfg: ScraperConfig) -> ParseStrategy:
        return BeautifulSoupStrategy() if cfg.use_parsing else RawHtmlStrategy()
