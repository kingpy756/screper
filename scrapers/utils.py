import logging
import sqlite3
import json
import time
import os
import functools
from typing import Any, Dict, List

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("manga_scraper")

# Try importing curl_cffi for Cloudflare bypass
try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None
    logger.warning("curl_cffi is not installed. Cloudflare bypassing might be less effective.")

import requests

class MangaCache:
    """SQLite-based local cache for manga metadata, chapters, and page lists."""
    def __init__(self, db_path: str = ".manga_cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        expires_at REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def get(self, key: str) -> Any:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    val_str, expires_at = row
                    if expires_at is None or expires_at > time.time():
                        return json.loads(val_str)
                    else:
                        cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                        conn.commit()
        except Exception as e:
            logger.warning(f"Cache get error for key '{key}': {e}")
        return None

    def set(self, key: str, value: Any, ttl: float = None):
        try:
            expires_at = time.time() + ttl if ttl else None
            val_str = json.dumps(value)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                    (key, val_str, expires_at)
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"Cache set error for key '{key}': {e}")

    def clear(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM cache")
                conn.commit()
            logger.info("Cache cleared successfully.")
        except Exception as e:
            logger.error(f"Cache clear error: {e}")

# Instantiated cache
cache = MangaCache()

def serialize_cache_value(value: Any) -> Any:
    """Helper to serialize model/objects into cache-compatible dictionaries."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return {"__type__": "Manga", "data": value.to_dict()}
    elif isinstance(value, list) and len(value) > 0 and hasattr(value[0], "to_dict"):
        return {"__type__": "List[Chapter]", "data": [item.to_dict() for item in value]}
    return value

def deserialize_cache_value(value: Any) -> Any:
    """Helper to deserialize dictionaries from cache back into model objects."""
    if isinstance(value, dict) and "__type__" in value:
        t = value["__type__"]
        data = value["data"]
        from models.manga import Manga
        from models.chapter import Chapter
        if t == "Manga":
            chapters = [Chapter(**c) for c in data.get("chapters", [])]
            data_copy = dict(data)
            data_copy["chapters"] = chapters
            return Manga(**data_copy)
        elif t == "List[Chapter]":
            return [Chapter(**c) for c in data]
    return value

def cached_method(ttl: float = 3600):
    """Decorator to cache method calls in BaseScraper implementations."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Args[0] is the scraper instance. Filter it out to build key.
            func_args = args[1:]
            key = f"{args[0].__class__.__name__}:{func.__name__}:{func_args}:{kwargs}"
            
            cached_val = cache.get(key)
            if cached_val is not None:
                logger.debug(f"Cache hit for key: {key}")
                return deserialize_cache_value(cached_val)
            
            result = func(*args, **kwargs)
            serialized = serialize_cache_value(result)
            cache.set(key, serialized, ttl)
            return result
        return wrapper
    return decorator


def fetch_html(url: str, use_playwright: bool = False, wait_selector: str = None, timeout_sec: int = 15) -> str:
    """
    Fetch raw HTML from a URL.
    Tries curl_cffi (with Chrome impersonation) or requests first, and falls back to
    Playwright if dynamic JS loading is requested, or if a Cloudflare challenge is detected.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive"
    }

    if not use_playwright:
        try:
            if curl_requests:
                logger.info(f"Fetching URL via curl_cffi: {url}")
                response = curl_requests.get(url, headers=headers, impersonate="chrome120", timeout=timeout_sec)
            else:
                logger.info(f"Fetching URL via standard requests: {url}")
                response = requests.get(url, headers=headers, timeout=timeout_sec)
                
            response.raise_for_status()
            html = response.text
            
            # Check for Cloudflare challenge
            if "cloudflare" in html.lower() and ("just a moment" in html.lower() or "checking your browser" in html.lower() or "enable javascript" in html.lower()):
                logger.warning("Cloudflare challenge page detected. Falling back to Playwright browser...")
                return fetch_html_playwright(url, wait_selector, timeout_sec * 1000)
                
            return html
        except Exception as e:
            logger.warning(f"Request failed with error: {e}. Falling back to Playwright browser...")

    return fetch_html_playwright(url, wait_selector, timeout_sec * 1000)


def fetch_html_playwright(url: str, wait_selector: str = None, timeout_ms: int = 20000) -> str:
    """Launches chromium headlessly to render dynamic content or bypass anti-bot screens."""
    logger.info(f"Launching Playwright to fetch: {url}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright is not installed. Cannot use Playwright fallback.")
        raise ImportError(
            "Playwright is needed for dynamic pages or Cloudflare fallback. "
            "Install it via: pip install playwright && playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            accept_downloads=False
        )
        page = context.new_page()
        try:
            # Set extra headers to look like a real user
            page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/"
            })
            page.goto(url, timeout=timeout_ms)
            
            # Wait for specific element, or let the page settle
            if wait_selector:
                logger.info(f"Playwright: Waiting for selector: {wait_selector}")
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            else:
                logger.info("Playwright: Allowing page JS to render (3s delay)")
                page.wait_for_timeout(3000)
                
            return page.content()
        except Exception as e:
            logger.error(f"Playwright fetching failed: {e}")
            raise e
        finally:
            browser.close()


def find_key_in_dict(d: Any, target_key: str) -> Any:
    """Recursively search for a key in a nested dictionary/list structure."""
    if isinstance(d, dict):
        if target_key in d:
            return d[target_key]
        for v in d.values():
            res = find_key_in_dict(v, target_key)
            if res is not None:
                return res
    elif isinstance(d, list):
        for item in d:
            res = find_key_in_dict(item, target_key)
            if res is not None:
                return res
    return None

