import abc

from datetime import datetime, timezone
from ..patterns.logger import AppLogger

log = AppLogger.get()


class ScrapeEvent:
    """Value object carrying event name, payload, and timestamp."""

    def __init__(self, name: str, payload: dict):
        self.name = name
        self.payload = payload
        self.timestamp = datetime.now(timezone.utc).isoformat()


class ScrapeObserver(abc.ABC):
    """Abstract observer. Implement on_event() to react."""

    @abc.abstractmethod
    def on_event(self, event: ScrapeEvent) -> None: ...


class LoggingObserver(ScrapeObserver):
    """Writes every event to the app logger."""

    _ICONS = {
        "url.start":   "→",
        "url.success": "✓",
        "url.error":   "✗",
        "url.skip":    "↷",
        "url.slow":    "⚠",
        "run.start":   "▶",
        "run.done":    "■",
    }

    def on_event(self, event: ScrapeEvent) -> None:
        icon = self._ICONS.get(event.name, "·")
        msg = event.payload.get("message", event.name)
        log.info("%s %s", icon, msg)


class SlowPageObserver(ScrapeObserver):
    """
    Feature #9 — Slow-page alerting.
    Fires url.slow and records the URL whenever a page exceeds the threshold.
    Keeps a list of slow pages accessible via .slow_pages for the summary.
    """

    def __init__(self, threshold_s: float):
        self._threshold = threshold_s
        self.slow_pages: list[dict] = []

    def on_event(self, event: ScrapeEvent) -> None:
        if event.name == "url.success":
            elapsed = event.payload.get("elapsed_s", 0)
            url = event.payload.get("url", "")
            if elapsed and elapsed >= self._threshold:
                self.slow_pages.append({"url": url, "elapsed_s": elapsed})
                log.warning(
                    "⚠ Slow page (%.1fs > %.1fs threshold): %s",
                    elapsed, self._threshold, url
                )


# Lightweight pub/sub. Scraper publishes; observers consume.
class EventBus:

    def __init__(self):
        self._observers: list[ScrapeObserver] = []

    def subscribe(self, obs: ScrapeObserver) -> None:
        self._observers.append(obs)

    def publish(self, name: str, **payload) -> None:
        event = ScrapeEvent(name, payload)
        for obs in self._observers:
            try:
                obs.on_event(event)
            except Exception as exc:
                log.warning("Observer %s raised: %s", type(obs).__name__, exc)
