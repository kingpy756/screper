import sys
import json
import argparse
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Query, HTTPException
import uvicorn

from scrapers.mangafire import MangaFireScraper
from scrapers.mangadot import MangaDotScraper
from scrapers.utils import logger

app = FastAPI(
    title="Manga Scraper API",
    description="A FastAPI web wrapper for mangafire.to and mangadot.net scrapers.",
    version="1.0.0"
)

def select_scraper_by_url(url: str):
    """Detect domain and return the appropriate scraper instance."""
    url_lower = url.lower()
    if "mangafire.to" in url_lower:
        return MangaFireScraper()
    elif "mangadot.net" in url_lower:
        return MangaDotScraper()
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL domain. Only https://mangafire.to and https://mangadot.net are supported."
        )

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Welcome to the Manga Scraper API. Use /docs for documentation.",
        "endpoints": {
            "/search": "Search for a manga by title. Query parameters: query (str), site (mangadot|mangafire|both)",
            "/info": "Fetch manga details and chapters. Query parameter: url (str)",
            "/pages": "Fetch page image URLs for a chapter. Query parameter: url (str)"
        }
    }

@app.get("/search")
def search_manga(
    query: str = Query(..., description="The title of the manga to search for"),
    site: str = Query("both", description="Specific site to search (mangafire, mangadot, or both)")
):
    site = site.lower()
    if site not in ["mangafire", "mangadot", "both"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid 'site' parameter. Must be 'mangafire', 'mangadot', or 'both'."
        )

    results = []
    if site in ["mangadot", "both"]:
        try:
            logger.info("Searching mangadot.net...")
            md_scraper = MangaDotScraper()
            md_results = md_scraper.search(query)
            for r in md_results:
                r["site"] = "mangadot"
            results.extend(md_results)
        except Exception as e:
            logger.error(f"MangaDot search failed: {e}")

    if site in ["mangafire", "both"]:
        try:
            logger.info("Searching mangafire.to...")
            mf_scraper = MangaFireScraper()
            mf_results = mf_scraper.search(query)
            for r in mf_results:
                r["site"] = "mangafire"
            results.extend(mf_results)
        except Exception as e:
            logger.error(f"MangaFire search failed: {e}")

    return results

@app.get("/info")
def get_manga_info(url: str = Query(..., description="The manga details page URL")):
    try:
        scraper = select_scraper_by_url(url)
        logger.info(f"Using scraper: {scraper.__class__.__name__}")
        manga = scraper.get_manga(url)
        return manga.to_dict()
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Failed to fetch manga info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pages")
def get_chapter_pages(url: str = Query(..., description="The chapter reader URL")):
    try:
        scraper = select_scraper_by_url(url)
        logger.info(f"Using scraper: {scraper.__class__.__name__}")
        pages_data = scraper.get_pages(url)
        return pages_data
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Failed to fetch pages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1, description="Search query")):
    import re
    try:
        md_scraper = MangaDotScraper()
        md_results = md_scraper.search(q)
        results = []
        for r in md_results:
            url = r.get("url", "")
            match = re.search(r'/manga/(\d+)', url)
            if match:
                m_id = int(match.group(1))
                results.append({
                    "id": m_id,
                    "title": r.get("title", ""),
                    "cover": r.get("cover", "")
                })
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        logger.error(f"API Search failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "results": []
        }

@app.get("/api/chapters")
def api_chapters(
    id: int = Query(..., description="Manga ID"),
    language: Optional[str] = Query("en", description="Language filter")
):
    import re
    try:
        md_scraper = MangaDotScraper()
        url = f"https://mangadot.net/manga/{id}"
        chapters_data = md_scraper.get_chapters(url)
        
        chapter_list = []
        for ch in chapters_data:
            ch_url = ch.url
            match = re.search(r'/chapter/(\d+)', ch_url)
            if not match:
                continue
            ch_id = int(match.group(1))
            
            chapter_list.append({
                "id": ch_id,
                "number": ch.number,
                "title": ch.title,
                "release_date": ch.release_date,
                "language": "en",
                "group": "Unknown"
            })
            
        lang = (language or "en").strip().lower()
        if lang != "all":
            chapter_list = [
                ch for ch in chapter_list
                if ch.get("language") == lang
            ]
            
        seen_numbers = set()
        deduped = []
        for ch in chapter_list:
            num = str(ch.get("number") or "").strip()
            if num not in seen_numbers:
                seen_numbers.add(num)
                deduped.append(ch)
                
        return {
            "success": True,
            "total": len(deduped),
            "chapters": deduped
        }
    except Exception as e:
        logger.error(f"API Chapters failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "total": 0,
            "chapters": []
        }

@app.get("/api/pages")
def api_pages(id: int = Query(..., description="Chapter ID")):
    try:
        md_scraper = MangaDotScraper()
        url = f"https://mangadot.net/chapter/{id}"
        pages_data = md_scraper.get_pages(url)
        return {
            "success": True,
            "pages": pages_data.get("pages", [])
        }
    except Exception as e:
        logger.error(f"API Pages failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "pages": []
        }

def run_cli():
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
            site = args.site
            results = []
            if site in ["mangadot", "both"]:
                try:
                    logger.info("Searching mangadot.net...")
                    md_scraper = MangaDotScraper()
                    md_results = md_scraper.search(args.query)
                    for r in md_results:
                        r["site"] = "mangadot"
                    results.extend(md_results)
                except Exception as e:
                    logger.error(f"MangaDot search failed: {e}")

            if site in ["mangafire", "both"]:
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
            # Direct CLI URL checking helper:
            url_lower = args.url.lower()
            if "mangafire.to" in url_lower:
                scraper = MangaFireScraper()
            elif "mangadot.net" in url_lower:
                scraper = MangaDotScraper()
            else:
                raise ValueError("Unsupported URL domain. Only mangafire.to and mangadot.net are supported.")
                
            logger.info(f"Using scraper: {scraper.__class__.__name__}")
            manga = scraper.get_manga(args.url)
            print(json.dumps(manga.to_dict(), indent=2, ensure_ascii=False))

        elif args.command == "pages":
            url_lower = args.url.lower()
            if "mangafire.to" in url_lower:
                scraper = MangaFireScraper()
            elif "mangadot.net" in url_lower:
                scraper = MangaDotScraper()
            else:
                raise ValueError("Unsupported URL domain. Only mangafire.to and mangadot.net are supported.")
                
            logger.info(f"Using scraper: {scraper.__class__.__name__}")
            pages_data = scraper.get_pages(args.url)
            print(json.dumps(pages_data, indent=2, ensure_ascii=False))

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # If any CLI arguments are passed (other than the file name itself), run the CLI parser
    if len(sys.argv) > 1:
        run_cli()
    else:
        # Default behavior when run directly without arguments: start the web API server
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
