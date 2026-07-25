# Modular Python Manga Scraper

A robust, modular, plugin-based Python manga scraper that supports searching, metadata extraction, chapter lists, and page image extraction from:
- [MangaDot](https://mangadot.net)
- [MangaFire](https://mangafire.to)

## Architecture

The project is structured with a modular, plugin-based design where all site-specific scrapers inherit from a common base class:

```
scrapers/
│
├── base.py       # Abstract BaseScraper interface
├── mangafire.py  # MangaFireScraper implementation
├── mangadot.py  # MangaDotScraper implementation
├── utils.py      # Network engine, SQLite cache, Cloudflare bypass
│
models/
├── manga.py      # Manga metadata dataclass
├── chapter.py    # Chapter dataclass
│
main.py           # CLI entry point with auto-detection registry
requirements.txt  # Dependencies list
```

## Features

- **Plugin-Based**: Easily add new scrapers by subclassing `BaseScraper` in `scrapers/` and registering them.
- **Domain Auto-detection**: The CLI automatically extracts the domain from target URLs to route requests to the correct scraper.
- **Robust Cache**: SQLite-backed transparent caching layer using a decorator `@cached_method(ttl=...)` that handles dataclass serialization automatically.
- **Impersonated Network Engine**: Attempts standard HTTP requests using `curl_cffi` (Chrome impersonation) to bypass Cloudflare challenges.
- **Playwright Fallback**: Automatically falls back to a headless Playwright browser to execute JavaScript if dynamic client-side rendering is required.
- **Interception Reader**: Listens to browser network traffic to intercept AJAX JSON responses directly, ensuring 100% accurate page image retrieval without having to emulate scrolls/swipes.

## Installation

1. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install Playwright browser engines:
   ```bash
   playwright install chromium
   ```

## Usage

Run the scraper using the CLI entry point `main.py`.

### 1. Search Manga by Title
Query one or both sites for a manga by title. Results return title, URL, cover image, and the originating site.
```bash
python main.py search "Solo Leveling"
```
Filter search to a single site:
```bash
python main.py search "One Piece" --site mangadot
python main.py search "One Piece" --site mangafire
```

### 2. Fetch Manga Metadata and Chapters
Specify a manga details URL. The CLI auto-detects the site and prints the full structured metadata and chapter list in JSON format.
```bash
python main.py info "https://mangadot.net/manga/41"
python main.py info "https://mangafire.to/manga/one-piece.lv1"
```

### 3. Fetch Chapter Page Image URLs
Get a sorted list of all page image URLs for a chapter.
```bash
python main.py pages "https://mangadot.net/chapter/1026494"
python main.py pages "https://mangafire.to/read/one-piece.lv1/en/chapter-1189"
```
