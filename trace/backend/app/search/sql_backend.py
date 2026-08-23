"""Search served directly from the event store.

No separate index: the store *is* the index. That keeps a small deployment to
one moving part and removes a whole class of bug — an index that has silently
drifted from the record it describes.

The trade is expressiveness, and it is declared rather than hidden: no fuzzy
matching, no wildcards, no relevance ranking. Results come back in time order,
which for forensic work is usually what you wanted anyway.
"""

from __future__ import annotations

from app.events.store import EventPage, EventQuery, EventStore, StoreCapabilities
from app.normalization.schema import NormalizedEvent
from app.search.backend import SearchBackend


class SqlSearchBackend(SearchBackend):
    name = "sql"

    def __init__(self, events: EventStore) -> None:
        self._events = events

    async def ping(self) -> bool:
        return await self._events.ping()

    async def available(self) -> tuple[bool, str]:
        ok = await self.ping()
        return ok, (
            f"Served directly from the {self._events.name} event store; no separate index."
            if ok
            else "The event store is unreachable."
        )

    def capabilities(self) -> StoreCapabilities:
        underlying = self._events.capabilities()
        return StoreCapabilities(
            name=self.name,
            full_text=underlying.full_text,
            fuzzy=False,
            wildcard=underlying.wildcard,
            regex=underlying.regex,
            aggregation=underlying.aggregation,
            notes=(
                f"Backed by the {self._events.name} event store. {underlying.notes} "
                "Results are ordered by time, not relevance."
            ),
        )

    async def ensure_indices(self) -> None:
        await self._events.ensure_schema()

    async def index_events(self, events: list[NormalizedEvent]) -> int:
        # Nothing to do: the store already holds them.
        return len(events)

    async def remove_evidence(self, tenant_id: str, evidence_id: str) -> int:
        return 0

    async def search(self, query: EventQuery) -> EventPage:
        page = await self._events.search(query)
        page.backend = self.name
        return page
