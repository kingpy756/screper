import re
import urllib.parse
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from models.manga import Manga
from models.chapter import Chapter
from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, cached_method, find_key_in_dict, logger

class MangaDotScraper(BaseScraper):
    BASE_URL = "https://mangadot.net"

    @cached_method(ttl=1800)
    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search manga by title on MangaDot."""
        # Try JSON data route first (fast)
        encoded_query = urllib.parse.quote_plus(query)
        search_data_url = f"{self.BASE_URL}/search.data?search={encoded_query}"
        results = []

        try:
            html = fetch_html(search_data_url, use_playwright=False)
            results = self._parse_search_json(html)
        except Exception as e:
            logger.warning(f"Standard JSON search failed: {e}. Falling back to Playwright DOM parsing...")

        # Fallback to Playwright DOM parsing if JSON search yielded no results
        if not results:
            search_page_url = f"{self.BASE_URL}/search?search={encoded_query}"
            html = fetch_html(search_page_url, use_playwright=True, wait_selector="a[href*='/manga/']")
            soup = BeautifulSoup(html, "html.parser")
            
            # Find cards: links containing /manga/
            for card in soup.select("a[href*='/manga/']"):
                href = card.get("href", "")
                url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                
                title_el = card.select_one("div.line-clamp-2, [class*='line-clamp']")
                title = title_el.text.strip() if title_el else card.text.strip()
                
                img_el = card.select_one("img")
                cover = img_el.get("src", "") if img_el else ""
                if cover and cover.startswith("/"):
                    cover = f"{self.BASE_URL}{cover}"
                
                # Exclude internal layout links that might match /manga/
                if title and url and "/manga/" in url and not any(r["url"] == url for r in results):
                    results.append({
                        "title": title,
                        "url": url,
                        "cover": cover
                    })
                    
        return results

    def _parse_search_json(self, text: str) -> List[Dict[str, Any]]:
        """Parser for search JSON and React Router RSC stream formats."""
        results = []
        # Match "id":118,"title":"Solo Leveling" or "id",118,"title","Solo Leveling"
        pattern = r'"id"\s*[,:]\s*(?P<id>\d+)\s*[,:]\s*"title"\s*[,:]\s*"(?P<title>[^"]+)"'
        matches = re.finditer(pattern, text)
        for m in matches:
            manga_id = m.group("id")
            title = m.group("title")
            
            # Search a 2000 character window forward for the cover photo
            snippet = text[m.end():m.end() + 2000]
            photo_match = re.search(r'"photo"\s*[,:]\s*"(?P<photo>[^"]+)"', snippet)
            photo = photo_match.group("photo") if photo_match else ""
            if photo and photo.startswith("/"):
                photo = f"{self.BASE_URL}{photo}"
                
            url = f"{self.BASE_URL}/manga/{manga_id}"
            if not any(r["url"] == url for r in results):
                results.append({
                    "title": title,
                    "url": url,
                    "cover": photo
                })
        return results

    @cached_method(ttl=3600)
    def get_manga(self, url: str) -> Manga:
        """Fetch manga details on MangaDot."""
        # Fetch raw HTML without Playwright since metadata is server-side rendered
        html = fetch_html(url, use_playwright=False)
        soup = BeautifulSoup(html, "html.parser")
        
        # Meta tags (very robust source of metadata)
        meta_title = soup.select_one('meta[property="og:title"]')
        title = meta_title.get("content", "").strip() if meta_title else ""
        if not title:
            title_el = soup.select_one("h1")
            title = title_el.text.strip() if title_el else "Unknown Title"
            
        meta_desc = soup.select_one('meta[name="description"]')
        description = meta_desc.get("content", "").strip() if meta_desc else ""
        if not description:
            desc_el = soup.select_one("div.text-sm.text-white/60")
            description = desc_el.text.strip() if desc_el else ""

        # Cover
        cover = ""
        preload_link = soup.select_one('link[rel="preload"][as="image"][href*="/uploads/"]')
        if preload_link:
            cover = preload_link.get("href", "")
        else:
            img_el = soup.select_one("img[src*='/uploads/']")
            cover = img_el.get("src", "") if img_el else ""
            
        if cover and cover.startswith("/"):
            cover = f"{self.BASE_URL}{cover}"
            
        # Alt titles (extracted from React Context if possible, otherwise empty list)
        alt_titles = []
        
        # Status
        status = ""
        status_span = soup.select_one("span[class*='text-green-500'], span[class*='text-blue-500']")
        if status_span:
            status = status_span.text.strip()
            
        # Genres
        genres = []
        for g in soup.select("a[href*='/search?search=']"):
            genres.append(g.text.strip())
            
        # Author & Artist
        author = ""
        artist = ""
        author_link = soup.select_one("a[href*='/search?author=']")
        if author_link:
            author = author_link.text.strip()
        artist_link = soup.select_one("a[href*='/search?artist=']")
        if artist_link:
            artist = artist_link.text.strip()
            
        # Rating
        rating = ""
        rating_span = soup.select_one("span[class*='text-amber-400']")
        if rating_span:
            # Extract rating value e.g. "★ 9.3/10" -> "9.3"
            rating = rating_span.text.replace("★", "").split("/")[0].strip()

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
        """Fetch chapters for a MangaDot URL."""
        logger.info(f"Retrieving chapters for MangaDot: {url}")
        
        # Extract manga ID from URL
        match = re.search(r'/manga/(\d+)', url)
        if not match:
            logger.warning(f"Could not extract manga ID from URL: {url}")
            return []
            
        manga_id = int(match.group(1))
        api_url = f"{self.BASE_URL}/api/manga/{manga_id}/chapters/list"
        logger.info(f"Fetching manga chapters list from: {api_url}")
        
        chapters = []
        try:
            # Fetch JSON list of chapters directly using standard fetch (no Playwright)
            html = fetch_html(api_url, use_playwright=False)
            import json
            chapters_data = json.loads(html)
            
            for item in chapters_data:
                ch_id = item.get("id")
                if not ch_id:
                    continue
                num_val = item.get("chapter_number")
                num = str(num_val) if num_val is not None else ""
                if not num:
                    continue
                title = item.get("chapter_title") or ""
                date_str = item.get("date_added") or ""
                release_date = date_str.split(" ")[0] if " " in date_str else date_str
                
                ch_url = f"{self.BASE_URL}/chapter/{ch_id}"
                chapters.append(Chapter(
                    number=num,
                    title=title.strip(),
                    url=ch_url,
                    release_date=release_date.strip()
                ))
        except Exception as e:
            logger.error(f"Failed to fetch chapters list from JSON API: {e}. Falling back to DOM parsing...")

        # Fallback to DOM parsing without Playwright
        if not chapters:
            logger.warning("Falling back to DOM parsing...")
            try:
                if not html_content:
                    html_content = fetch_html(url, use_playwright=False)
                soup = BeautifulSoup(html_content, "html.parser")
                
                # Find links containing /chapter/
                links = soup.select("a[href*='/chapter/']")
                for link in links:
                    href = link.get("href", "")
                    ch_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                    
                    # Extract chapter ID from URL to validate link format
                    match_ch = re.search(r'/chapter/(\d+)', ch_url)
                    if not match_ch:
                        continue
                        
                    # Check for chapter number inside spans (e.g. "Ch 1189")
                    num_el = link.select_one("span[class*='text-white/85']")
                    number = num_el.text.strip() if num_el else ""
                    number = re.sub(r'^[Cc]h\s*', '', number)
                    
                    title_el = link.select_one("span[class*='text-white/95']")
                    title = title_el.text.strip() if title_el else ""
                    
                    date_el = link.select_one("span[class*='text-white/45']")
                    release_date = date_el.text.strip() if date_el else ""
                    
                    if ch_url and not any(c.url == ch_url for c in chapters):
                        chapters.append(Chapter(
                            number=number,
                            title=title,
                            url=ch_url,
                            release_date=release_date
                        ))
            except Exception as dom_err:
                logger.error(f"DOM fallback failed: {dom_err}")
                
        # Preserve ascending page order (oldest to newest)
        try:
            if len(chapters) > 1:
                # Clean up numbers for comparisons
                num_first = float(re.findall(r'[\d.]+', chapters[0].number)[0])
                num_last = float(re.findall(r'[\d.]+', chapters[-1].number)[0])
                if num_first > num_last:
                    chapters.reverse()
        except Exception:
            chapters.reverse()
            
        return chapters

    @cached_method(ttl=3600)
    def get_pages(self, chapter_url: str) -> Dict[str, List[str]]:
        """Fetch all page image URLs for a specific chapter on MangaDot."""
        # Extract chapter ID from URL
        match = re.search(r'/chapter/(\d+)', chapter_url)
        if not match:
            raise ValueError(f"Invalid chapter URL format: {chapter_url}")
            
        chapter_id = match.group(1)
        api_url = f"{self.BASE_URL}/api/chapters/{chapter_id}/images"
        
        logger.info(f"[get_pages] Querying MangaDot chapter images API: {api_url} for chapter_id: {chapter_id}")
        
        pages = []
        try:
            # Load API payload using standard fetch
            html = fetch_html(api_url, use_playwright=False)
            import json
            data = json.loads(html)
            
            # --- Validate the response belongs to the requested chapter ---
            response_chapter = data.get("chapter", {})
            response_chapter_id = response_chapter.get("id")
            response_manga_title = data.get("manga", {}).get("title", "unknown")
            
            logger.info(
                f"[get_pages] Response: chapter_id={response_chapter_id}, "
                f"manga_title='{response_manga_title}', page_count={response_chapter.get('page_count')}"
            )
            
            if response_chapter_id is not None and int(response_chapter_id) != int(chapter_id):
                logger.error(
                    f"[get_pages] CHAPTER ID MISMATCH! Requested chapter_id={chapter_id} "
                    f"but API returned chapter_id={response_chapter_id} "
                    f"(manga: '{response_manga_title}'). Discarding response."
                )
            else:
                for img in data.get("images", []):
                    url_path = img.get("url", "")
                    if url_path:
                        full_url = f"{self.BASE_URL}{url_path}" if url_path.startswith("/") else url_path
                        pages.append(full_url)
                logger.info(f"[get_pages] Extracted {len(pages)} page images from API for chapter_id={chapter_id}")
        except Exception as e:
            logger.warning(f"[get_pages] Failed to parse images API JSON ({e}). Falling back to HTML parsing...")
            
        # HTML fallback
        if not pages:
            try:
                logger.info(f"[get_pages] HTML fallback: fetching {chapter_url}")
                html = fetch_html(chapter_url, use_playwright=False)
                soup = BeautifulSoup(html, "html.parser")
                
                # Validate canonical URL matches the requested chapter
                canonical = soup.select_one("link[rel='canonical']")
                if canonical:
                    canonical_href = canonical.get("href", "")
                    if f"/chapter/{chapter_id}" not in canonical_href:
                        logger.error(
                            f"[get_pages] HTML fallback canonical URL mismatch! "
                            f"Expected /chapter/{chapter_id}, got '{canonical_href}'. Aborting fallback."
                        )
                        return {"pages": []}
                
                for img in soup.select("img"):
                    src = img.get("src") or img.get("data-src")
                    # Only match actual chapter page images (from /chapters/ path),
                    # NOT cover art or other uploads (from /uploads/ path)
                    if src and "/chapters/" in src:
                        full_url = f"{self.BASE_URL}{src}" if src.startswith("/") else src
                        if full_url not in pages:
                            pages.append(full_url)
                logger.info(f"[get_pages] HTML fallback extracted {len(pages)} page images for chapter_id={chapter_id}")
            except Exception as e:
                logger.error(f"[get_pages] HTML fallback failed for chapter_id={chapter_id}: {e}")
                
        return {"pages": pages}
