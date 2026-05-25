"""Singleton logger. One instance, shared everywhere."""

from typing import Optional
import logging


class AppLogger:
    _instance: Optional[logging.Logger] = None

    def __new__(cls):
        raise TypeError("Use AppLogger.get()")

    @classmethod
    def get(cls, level: str = "INFO") -> logging.Logger:
        if cls._instance is None:
            fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
            logging.basicConfig(
                format=fmt, datefmt="%Y-%m-%d %H:%M:%S", level=level
            )
            cls._instance = logging.getLogger("Iki_Scraper")
        return cls._instance
