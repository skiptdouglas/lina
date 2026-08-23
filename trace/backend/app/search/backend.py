"""Search backend abstraction.

Search and event storage are separate concerns: the event store is the record,
a search backend is an index over it. They are split because OpenSearch offers
things a columnar store does not (relevance ranking, fuzzy matching, analyzers)
and because an index can be rebuilt from the store at any time, which is what
makes it safe to treat as disposable.

Both implementations report :class:`~app.events.store.StoreCapabilities`, and
the API passes that through. An analyst must always be able to tell "nothing
matched" from "this backend cannot express that query" — the difference
between an investigative conclusion and a tooling limitation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.events.store import EventPage, EventQuery, StoreCapabilities
from app.normalization.schema import NormalizedEvent


class SearchBackend(ABC):
    name: str

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def available(self) -> tuple[bool, str]:
        """``(usable, reason)``. Never raises."""

    @abstractmethod
    def capabilities(self) -> StoreCapabilities: ...

    @abstractmethod
    async def ensure_indices(self) -> None: ...

    @abstractmethod
    async def index_events(self, events: list[NormalizedEvent]) -> int:
        """Add events to the index. Idempotent on ``event_id``."""

    @abstractmethod
    async def remove_evidence(self, tenant_id: str, evidence_id: str) -> int:
        """Drop an artifact's events so a re-parse does not duplicate them."""

    @abstractmethod
    async def search(self, query: EventQuery) -> EventPage: ...
