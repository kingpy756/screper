from abc import ABC, abstractmethod
from typing import List, Dict, Any
from models.manga import Manga
from models.chapter import Chapter

class BaseScraper(ABC):
    @abstractmethod
    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Search manga by title.
        Returns a list of dictionaries, e.g., [{"title": "...", "url": "..."}].
        """
        pass

    @abstractmethod
    def get_manga(self, url: str) -> Manga:
        """
        Fetch manga information and basic metadata.
        Returns a Manga model object.
        """
        pass

    @abstractmethod
    def get_chapters(self, url: str) -> List[Chapter]:
        """
        Fetch the list of chapters for a manga URL.
        Returns a list of Chapter model objects.
        """
        pass

    @abstractmethod
    def get_pages(self, chapter_url: str) -> Dict[str, List[str]]:
        """
        Fetch all page image URLs for a specific chapter, preserving the correct order.
        Returns a dictionary in the format: {"pages": ["image_url_1", "image_url_2", ...]}
        """
        pass
