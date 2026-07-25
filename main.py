import sys
import json
import argparse
from typing import List, Dict, Any

from scrapers.mangafire import MangaFireScraper
from scrapers.mangadot import MangaDotScraper
from scrapers.utils import logger

def select_scraper_by_url(url: str):
    """Detect domain and return the appropriate scraper instance."""
    url_lower = url.lower()
    if "mangafire.to" in url_lower:
        return MangaFireScraper()
    elif "mangadot.net" in url_lower:
        return MangaDotScraper()
    else:
        raise ValueError("Unsupported URL domain. Only https://mangafire.to and https://mangadot.net are supported.")

def main():
    parser = argparse.ArgumentParser(
        description="Modular Python Manga Scraper CLI for mangafire.to and mangadot.net"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Search Command
    search_parser = subparsers.add_parser("search", help="Search for a manga by title")
    search_parser.add_argument("query", type=str, help="Search query/title")
    search_parser.add_argument(
        "--site", "-s",
        choices=["mangafire", "mangadot", "both"],
        default="both",
        help="Specific site to search (default: both)"
    )

    # Info Command
    info_parser = subparsers.add_parser("info", help="Fetch manga details and chapters")
    info_parser.add_argument("url", type=str, help="Manga details URL")

    # Pages Command
    pages_parser = subparsers.add_parser("pages", help="Fetch all page image URLs for a chapter")
    pages_parser.add_argument("url", type=str, help="Chapter reader URL")

    args = parser.parse_args()

    try:
        if args.command == "search":
            results = []
            if args.site in ["mangadot", "both"]:
                try:
                    logger.info("Searching mangadot.net...")
                    md_scraper = MangaDotScraper()
                    md_results = md_scraper.search(args.query)
                    for r in md_results:
                        r["site"] = "mangadot"
                    results.extend(md_results)
                except Exception as e:
                    logger.error(f"MangaDot search failed: {e}")

            if args.site in ["mangafire", "both"]:
                try:
                    logger.info("Searching mangafire.to...")
                    mf_scraper = MangaFireScraper()
                    mf_results = mf_scraper.search(args.query)
                    for r in mf_results:
                        r["site"] = "mangafire"
                    results.extend(mf_results)
                except Exception as e:
                    logger.error(f"MangaFire search failed: {e}")

            print(json.dumps(results, indent=2, ensure_ascii=False))

        elif args.command == "info":
            scraper = select_scraper_by_url(args.url)
            logger.info(f"Using scraper: {scraper.__class__.__name__}")
            manga = scraper.get_manga(args.url)
            print(json.dumps(manga.to_dict(), indent=2, ensure_ascii=False))

        elif args.command == "pages":
            scraper = select_scraper_by_url(args.url)
            logger.info(f"Using scraper: {scraper.__class__.__name__}")
            pages_data = scraper.get_pages(args.url)
            print(json.dumps(pages_data, indent=2, ensure_ascii=False))

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
