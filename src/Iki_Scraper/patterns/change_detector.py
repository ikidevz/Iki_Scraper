"""
Detects whether page content has changed since the last scrape.
Stores SHA-256 hashes in a JSON file next to the output dir.
Strategy: can be swapped for a Redis or DB-backed implementation.
"""

import json
import hashlib

from pathlib import Path
from ..patterns.logger import AppLogger

log = AppLogger.get()


class ChangeDetector:
    def __init__(self, output_dir: str):
        self._path = Path(output_dir) / ".content_hashes.json"
        self._hashes: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._hashes, indent=2))

    def has_changed(self, url: str, html: str) -> bool:
        """Return True if content is new or different from last seen."""
        new_hash = hashlib.sha256(html.encode()).hexdigest()
        old_hash = self._hashes.get(url)
        if old_hash == new_hash:
            log.info("· Unchanged %s — skipping save", url)
            return False
        self._hashes[url] = new_hash
        self._save()
        return True
