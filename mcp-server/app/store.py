"""In-memory GUID -> Quote store (POC-grade, no persistence).

GUIDs are random uuid4s, not sequential — handoff links cannot be enumerated.
"""

from __future__ import annotations

import uuid

from app.models import Quote


class QuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}

    def save(self, quote: Quote) -> str:
        guid = str(uuid.uuid4())
        self._quotes[guid] = quote
        return guid

    def get(self, guid: str) -> Quote | None:
        return self._quotes.get(guid)
