from dataclasses import dataclass, asdict

@dataclass
class Chapter:
    number: str
    title: str
    url: str
    release_date: str

    def to_dict(self) -> dict:
        return asdict(self)
