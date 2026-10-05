"""Common job record shared by every source adapter."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Location:
    city: str = ""
    state: str = ""
    country: str = ""

    def text(self) -> str:
        return ", ".join(p for p in (self.city, self.state, self.country) if p)


@dataclass
class Job:
    source: str                       # "joe" | "ejm"
    source_id: str
    url: str
    title: str
    institution: str
    department: str = ""
    section: str = ""                 # raw position type / section text from the source
    locations: list[Location] = field(default_factory=list)
    jel_codes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)   # free-text fields/keywords
    deadline: Optional[str] = None    # ISO yyyy-mm-dd
    posted: Optional[str] = None      # ISO yyyy-mm-dd
    start_date_text: str = ""
    degree_required: str = ""
    requirements: list[str] = field(default_factory=list)
    salary: str = ""
    full_text: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d
