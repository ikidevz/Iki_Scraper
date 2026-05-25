
"""
Persists completed URLs to a JSON file so re-runs skip already-done work.
Lives next to the output dir as .checkpoint.json.
"""

from pathlib import Path
import json


class CheckpointStore:
    def __init__(self, output_dir: str):
        self._path = Path(output_dir) / ".checkpoint.json"
        self._done: set[str] = self._load()

    def _load(self) -> set[str]:
        if self._path.exists():
            try:
                return set(json.loads(self._path.read_text()))
            except Exception:
                return set()
        return set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(sorted(self._done), indent=2))

    def is_done(self, url: str) -> bool:
        return url in self._done

    def mark_done(self, url: str) -> None:
        self._done.add(url)
        self._save()

    def clear(self) -> None:
        self._done.clear()
        self._save()
