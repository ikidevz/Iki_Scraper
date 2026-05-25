import abc
import json
import re
import sqlite3

from pathlib import Path
from ..patterns.logger import AppLogger

log = AppLogger.get()


class OutputRepository(abc.ABC):
    """Abstract persistence layer. Swap to S3/GCS/DB by subclassing."""

    @abc.abstractmethod
    def save_html(self, filename: str, html: str) -> str: ...

    @abc.abstractmethod
    def save_meta(self, filename: str, meta: dict) -> str: ...

    @abc.abstractmethod
    def save_summary(self, summary: dict) -> str: ...

    @abc.abstractmethod
    def filename_for(self, url: str) -> str: ...


class LocalFileRepository(OutputRepository):
    """Writes .html and _meta.json to the local filesystem."""

    def __init__(self, output_dir: str):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(url: str) -> str:
        name = re.sub(r"https?://", "", url)
        name = re.sub(r"[^\w\-]", "_", name)
        return name[:120]

    def filename_for(self, url: str) -> str:
        return self._safe_name(url)

    def save_html(self, filename: str, html: str) -> str:
        p = self._dir / f"{filename}.html"
        p.write_text(html, encoding="utf-8")
        return str(p)

    def save_meta(self, filename: str, meta: dict) -> str:
        p = self._dir / f"{filename}_meta.json"
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return str(p)

    def save_summary(self, summary: dict) -> str:
        p = self._dir / "scrape_summary.json"
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        return str(p)


class SQLiteRepository(OutputRepository):
    """
    Feature #5 — SQLite backend.
    Stores every page in a local SQLite DB alongside (or instead of) flat files.
    Schema: pages(url, filename, timestamp, http_status, size_bytes, meta_json, html)
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS pages (
        url          TEXT PRIMARY KEY,
        filename     TEXT,
        timestamp    TEXT,
        http_status  INTEGER,
        size_bytes   INTEGER,
        meta_json    TEXT,
        html         TEXT
    );
    CREATE TABLE IF NOT EXISTS runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at   TEXT,
        finished_at  TEXT,
        elapsed_s    REAL,
        total        INTEGER,
        success      INTEGER,
        error        INTEGER,
        summary_json TEXT
    );
    """

    def __init__(self, db_path: str):
        self._path = db_path
        con = sqlite3.connect(db_path)
        con.executescript(self._DDL)
        con.commit()
        con.close()
        log.info("SQLite backend: %s", db_path)

    @staticmethod
    def _safe_name(url: str) -> str:
        name = re.sub(r"https?://", "", url)
        name = re.sub(r"[^\w\-]", "_", name)
        return name[:120]

    def filename_for(self, url: str) -> str:
        return self._safe_name(url)

    def save_html(self, filename: str, html: str) -> str:
        # HTML is stored in the DB; return a logical key
        return f"sqlite://{self._path}#{filename}"

    def save_meta(self, filename: str, meta: dict) -> str:
        con = sqlite3.connect(self._path)
        con.execute(
            """INSERT OR REPLACE INTO pages
               (url, filename, timestamp, http_status, size_bytes, meta_json)
               VALUES (:url,:fn,:ts,:status,:size,:meta)""",
            {
                "url":    meta.get("url", ""),
                "fn":     filename,
                "ts":     meta.get("timestamp", ""),
                "status": meta.get("http_status"),
                "size":   meta.get("size_bytes", 0),
                "meta":   json.dumps(meta),
            },
        )
        con.commit()
        con.close()
        return f"sqlite://{self._path}#{filename}_meta"

    def save_summary(self, summary: dict) -> str:
        con = sqlite3.connect(self._path)
        con.execute(
            """INSERT INTO runs
               (started_at, finished_at, elapsed_s, total, success, error, summary_json)
               VALUES (?,?,?,?,?,?,?)""",
            (
                summary.get("started_at"),
                summary.get("finished_at"),
                summary.get("elapsed_s"),
                summary.get("total"),
                summary.get("success"),
                summary.get("error"),
                json.dumps(summary),
            ),
        )
        con.commit()
        con.close()
        return f"sqlite://{self._path}#runs"

    def upsert_html(self, url: str, html: str) -> None:
        """Called separately to store HTML body in SQLite."""
        con = sqlite3.connect(self._path)
        con.execute(
            "UPDATE pages SET html=? WHERE url=?", (html, url)
        )
        con.commit()
        con.close()


class CompositeRepository(OutputRepository):
    """
    Writes to both LocalFileRepository and SQLiteRepository simultaneously.
    80/20: lets you keep flat files (easy to read) and SQLite (easy to query).
    """

    def __init__(self, file_repo: LocalFileRepository, db_repo: SQLiteRepository):
        self._file = file_repo
        self._db = db_repo

    def filename_for(self, url: str) -> str:
        return self._file.filename_for(url)

    def save_html(self, filename: str, html: str) -> str:
        self._db.save_html(filename, html)
        return self._file.save_html(filename, html)

    def save_meta(self, filename: str, meta: dict) -> str:
        self._db.save_meta(filename, meta)
        return self._file.save_meta(filename, meta)

    def save_summary(self, summary: dict) -> str:
        self._db.save_summary(summary)
        return self._file.save_summary(summary)
