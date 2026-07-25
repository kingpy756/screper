from dataclasses import dataclass, field, asdict
from typing import List
from .chapter import Chapter

@dataclass
class Manga:
    title: str
    alt_titles: List[str] = field(default_factory=list)
    description: str = ""
    cover: str = ""
    status: str = ""
    genres: List[str] = field(default_factory=list)
    author: str = ""
    artist: str = ""
    rating: str = ""
    chapters: List[Chapter] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chapters"] = [c.to_dict() for c in self.chapters]
        return d
