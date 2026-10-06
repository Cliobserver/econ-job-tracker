"""Per-source notes surfaced in the health table (e.g. 'cached feed', 'imap: 3 new')."""
from __future__ import annotations

NOTES: dict[str, str] = {}


def note(source: str, text: str) -> None:
    NOTES[source] = text
