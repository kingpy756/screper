import re
import urllib.parse
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from models.manga import Manga
from models.chapter import Chapter
from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, cached_method, find_key_in_dict, logger

class MangaFireScraper(BaseScraper):
    BASE_URL = "https://mangafire.to"

    @cached_method(ttl=1800)
    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search manga by title on MangaFire."""
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"{self.BASE_URL}/browse?keyword={encoded_query}"
        
        # Wait specifically for the search results cards to render (avoids race condition with static widgets)
        html = fetch_html(
            search_url, 
            use_playwright=True, 
            wait_selector=".browse__results a.title-grid__link, .browse__results a.title-rows__link"
        )
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # Parse List/Rows layout cards (default view)
        for card in soup.select(".browse__results a.title-rows__link"):
            href = card.get("href", "")
            url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            
            title_el = card.select_one(".title-row-card__title")
            title = title_el.text.strip() if title_el else ""
            
            img_el = card.select_one(".title-row-card__poster img")
            cover = img_el.get("src", "") if img_el else ""
            
            if title and url:
                results.append({
                    "title": title,
                    "url": url,
                    "cover": cover
                })

        # Parse Grid layout cards
        for card in soup.select(".browse__results a.title-grid__link"):
            href = card.get("href", "")
            url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            
            title_el = card.select_one(".manga-card__title")
            title = title_el.text.strip() if title_el else ""
            
            img_el = card.select_one("img.manga-card__img")
            cover = img_el.get("src", "") if img_el else ""
            
            # Deduplicate by URL
            if title and url and not any(r["url"] == url for r in results):
                results.append({
                    "title": title,
                    "url": url,
                    "cover": cover
                })

        return results

    @cached_method(ttl=3600)
    def get_manga(self, url: str) -> Manga:
        """Fetch manga details on MangaFire."""
        html = fetch_html(url, use_playwright=True, wait_selector="h1.title-detail__title")
        soup = BeautifulSoup(html, "html.parser")
        
        title_el = soup.select_one("h1.title-detail__title")
        title = title_el.text.strip() if title_el else "Unknown Title"
        
        # Alternative titles
        alt_titles = []
        alt_text_el = soup.select_one("span.title-detail__alt-text")
        if alt_text_el:
            alt_titles = [name.strip() for name in alt_text_el.text.split("·") if name.strip()]
        else:
            alt_lines = soup.select(".title-detail__alt-list-inner span.title-detail__alt-line")
            alt_titles = [line.text.strip() for line in alt_lines if line.text.strip()]

        # Description
        desc_el = soup.select_one("div.title-detail__synopsis")
        description = desc_el.text.strip() if desc_el else ""
        
        # Cover image
        cover_el = soup.select_one(".title-detail__poster img")
        cover = cover_el.get("src", "") if cover_el else ""
        if cover and cover.startswith("/"):
            cover = f"{self.BASE_URL}{cover}"
            
        # Status
        status_el = soup.select_one(".badge--status")
        status = status_el.text.strip() if status_el else ""
        
        # Genres
        genres = [tag.text.strip() for tag in soup.select("a.title-detail__tag")]
        
        # Author & Artist
        author = ""
        artist = ""
        credits_a = soup.select(".title-detail__credits a")
        for a in credits_a:
            href = a.get("href", "")
            if "authors" in href:
                author = a.text.strip()
            elif "artists" in href:
                artist = a.text.strip()
                
        # Rating
        rating = ""
        rating_el = soup.select_one(".title-detail__meta-stats span")
        if rating_el:
            # Extract rating value e.g. "★ 9.8" -> "9.8"
            rating = rating_el.text.replace("★", "").strip()

        # Fetch chapters list using current page context
        chapters = self.get_chapters(url, html_content=html)

        return Manga(
            title=title,
            alt_titles=alt_titles,
            description=description,
            cover=cover,
            status=status,
            genres=genres,
            author=author,
            artist=artist,
            rating=rating,
            chapters=chapters
        )

    @cached_method(ttl=3600)
    def get_chapters(self, url: str, html_content: str = None) -> List[Chapter]:
        """Fetch chapters for a MangaFire URL."""
        if not html_content:
            html_content = fetch_html(url, use_playwright=True, wait_selector="a.title-detail__row-link")
            
        soup = BeautifulSoup(html_content, "html.parser")
        chapters = []
        
        # Each chapter row contains a link
        rows = soup.select("a.title-detail__row-link")
        for row in rows:
            href = row.get("href", "")
            ch_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            
            # Chapter number
            num_el = row.select_one(".title-detail__row-num")
            number = num_el.text.strip() if num_el else ""
            # Strip "Ch. " prefix if present
            number = re.sub(r'^[Cc]h\.\s*', '', number)
            
            # Chapter title
            title_el = row.select_one(".title-detail__row-sub")
            title = title_el.text.strip() if title_el else ""
            
            # Release date is normally adjacent in the row element's parent container
            parent = row.parent
            release_date = ""
            if parent:
                # Find sibling spans or generic text content that aren't the main link text
                texts = [child.text.strip() for child in parent.children if child != row and child.text.strip()]
                if texts:
                    release_date = texts[0]

            if ch_url:
                chapters.append(Chapter(
                    number=number,
                    title=title,
                    url=ch_url,
                    release_date=release_date
                ))
                
        # Preserve ascending page order (oldest to newest)
        try:
            if len(chapters) > 1:
                num_first = float(re.findall(r'[\d.]+', chapters[0].number)[0])
                num_last = float(re.findall(r'[\d.]+', chapters[-1].number)[0])
                if num_first > num_last:
                    chapters.reverse()
        except Exception:
            chapters.reverse()
            
        return chapters

    @cached_method(ttl=3600)
    def get_pages(self, chapter_url: str) -> Dict[str, List[str]]:
        """Fetch all page image URLs for a specific chapter on MangaFire."""
        logger.info(f"Fetching pages via Playwright network interception: {chapter_url}")
        pages = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Intercept response of the api call that delivers encrypted pages/JSON
            def handle_response(response):
                if "api/chapters" in response.url:
                    try:
                        data = response.json()
                        found_pages = find_key_in_dict(data, "pages")
                        if found_pages and isinstance(found_pages, list):
                            for item in found_pages:
                                if isinstance(item, dict) and 'url' in item:
                                    pages.append(item['url'])
                                elif isinstance(item, str):
                                    pages.append(item)
                    except Exception as e:
                        logger.debug(f"Interception JSON decode failed: {e}")

            page.on("response", handle_response)
            try:
                page.goto(chapter_url, timeout=30000)
                # Wait for the reader element to be visible
                page.wait_for_selector(".swiper-wrapper, img.reader-img", timeout=15000)
                page.wait_for_timeout(3000) # Give extra time to ensure request is complete
            except Exception as e:
                logger.warning(f"Timeout waiting for reader pages to load: {e}")
            finally:
                browser.close()
                
        # DOM fallback if network interception yielded no URLs
        if not pages:
            logger.warning("Network interception failed. Falling back to DOM parsing...")
            html = fetch_html(chapter_url, use_playwright=True, wait_selector="img.reader-img")
            soup = BeautifulSoup(html, "html.parser")
            for img in soup.select("img.reader-img, img.reader-swiper__img"):
                src = img.get("src") or img.get("data-src")
                if src and src not in pages:
                    pages.append(src)
                    
        return {"pages": pages}
