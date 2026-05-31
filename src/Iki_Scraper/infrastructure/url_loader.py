"""
url_loader.py — URL list input parsing
=======================================
Parses .txt (one URL per line, # comments) and .json (list of strings)
files into a plain list of URL strings.
"""

from __future__ import annotations

import json
from pathlib import Path


class UrlLoader:
    """Parses a .txt or .json URL list file into a list of strings."""

    @staticmethod
    def from_file(path: str) -> list[str]:
        """
        Load URLs from a file.

        Supported formats:

        * ``.txt`` — one URL per line; lines starting with ``#`` are comments,
          blank lines are ignored.
        * ``.json`` — a JSON array of URL strings.

        Args:
            path: Path to the URL list file.

        Returns:
            List of URL strings.

        Raises:
            ValueError: If a .json file does not contain a top-level list.
            FileNotFoundError: If *path* does not exist.
        """
        p = Path(path)
        if p.suffix == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError(
                    "JSON URL file must contain a list of URL strings."
                )
            return [str(u) for u in data]

        return [
            line.strip()
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
