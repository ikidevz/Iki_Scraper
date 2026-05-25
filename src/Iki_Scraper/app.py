from __future__ import annotations

import argparse
import json
import sys


from Iki_Scraper import (
    AppLogger,
    ScraperFacade,
    ScraperConfig,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="Iki_Scraper",
        description="Async Playwright web scraper — OOP + 9 features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py --url https://example.com
  python main.py --urls https://a.com https://b.com --use-parsing
  python main.py --file urls.txt --concurrency 5 --resumable
  python main.py --sitemap https://example.com --use-sqlite
        """,
    )

    # ── Input mode (mutually exclusive — pick exactly one) ────────────────────
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--url",
        metavar="URL",
        help="Scrape a single URL",
    )
    grp.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="Scrape two or more URLs (space-separated)",
    )
    grp.add_argument(
        "--file",
        metavar="PATH",
        help="Load URLs from a .txt (one per line) or .json (list) file",
    )
    grp.add_argument(
        "--sitemap",
        metavar="BASE_URL",
        help="Discover sitemap.xml then scrape all URLs found",
    )

    # ── Output ────────────────────────────────────────────────────────────────
    out = ap.add_argument_group("output")
    out.add_argument(
        "--output-dir",
        default="scraper_output",
        metavar="DIR",
        help="Directory for .html, _meta.json, and summary files (default: scraper_output)",
    )
    out.add_argument(
        "--use-parsing",
        action="store_true",
        help="Enable BeautifulSoup extraction: title, meta, text, tables",
    )
    out.add_argument(
        "--use-sqlite",
        action="store_true",
        help="Also write all results to a local SQLite database",
    )
    out.add_argument(
        "--sqlite-path",
        default="scraper.db",
        metavar="PATH",
        help="SQLite database file path (default: scraper.db)",
    )

    # ── Browser ───────────────────────────────────────────────────────────────
    browser = ap.add_argument_group("browser")
    browser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        metavar="N",
        help="Max parallel browser contexts (default: 3)",
    )
    browser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging)",
    )
    browser.add_argument(
        "--use-proxies",
        action="store_true",
        help="Rotate free proxies from ProxyScrape",
    )

    # ── Resilience ────────────────────────────────────────────────────────────
    resilience = ap.add_argument_group("resilience")
    resilience.add_argument(
        "--resumable",
        action="store_true",
        help="Skip URLs already completed in a previous run (.checkpoint.json)",
    )
    resilience.add_argument(
        "--skip-unchanged",
        action="store_true",
        help="Skip saving pages whose HTML hash matches the previous run",
    )
    resilience.add_argument(
        "--max-retries",
        type=int,
        default=3,
        metavar="N",
        help="Retry attempts on failure with exponential backoff (default: 3, 0=off)",
    )
    resilience.add_argument(
        "--domain-rate",
        type=float,
        default=0.0,
        metavar="SECS",
        help="Minimum seconds between requests to the same domain (default: 0 = off)",
    )

    # ── Observability ─────────────────────────────────────────────────────────
    obs = ap.add_argument_group("observability")
    obs.add_argument(
        "--slow-threshold",
        type=float,
        default=10.0,
        metavar="SECS",
        help="Flag pages that take longer than N seconds (default: 10)",
    )
    obs.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO)",
    )

    return ap


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    # Initialise singleton logger at requested level before anything else
    log = AppLogger.get(args.log_level)

    # Build config from parsed args — one field per argument, no repetition
    cfg = ScraperConfig(
        output_dir=args.output_dir,
        use_parsing=args.use_parsing,
        use_sqlite=args.use_sqlite,
        sqlite_path=args.sqlite_path,
        max_concurrency=args.concurrency,
        headless=not args.no_headless,
        use_proxies=args.use_proxies,
        resumable=args.resumable,
        skip_unchanged=args.skip_unchanged,
        max_retries=args.max_retries,
        domain_rate_limit=args.domain_rate,
        slow_page_threshold_sec=args.slow_threshold,
    )

    facade = ScraperFacade(cfg)

    # ── Dispatch to the correct scrape method ─────────────────────────────────
    if args.sitemap:
        summary = facade.scrape_sitemap(args.sitemap)
    elif args.url:
        summary = facade.scrape_one(args.url)
    elif args.urls:
        summary = facade.scrape_many(args.urls)
    else:
        summary = facade.scrape_file(args.file)

    if facade.slow_pages:
        log.warning("Slow pages detected (%d):", len(facade.slow_pages))
        for sp in facade.slow_pages:
            log.warning("  %.1fs  %s", sp["elapsed_s"], sp["url"])

    print(json.dumps(
        {
            "success":    summary["success"],
            "error":      summary["error"],
            "skipped":    summary.get("skipped", 0),
            "unchanged":  summary.get("unchanged", 0),
            "slow_pages": len(facade.slow_pages),
        },
        indent=2,
    ))

    return 0 if summary["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
