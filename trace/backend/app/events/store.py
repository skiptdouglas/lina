"""Event store abstraction.

ClickHouse owns normalized events in production (ADR-0002). This interface
exposes **typed query methods** rather than raw SQL, for one reason: SQL
written for ClickHouse does not run anywhere else, and an interface whose only
method is ``execute(sql)`` is not actually replaceable — it just moves the
coupling.

Each implementation writes its own SQL and pushes aggregation into its own
engine, which is what ADR-0002 asks for. What travels across the interface is
a query description, not a query.

Two implementations ship:

* :class:`~app.events.sql_store.SqlEventStore` — SQLAlchemy over the metadata
  database. Correct everywhere, no extra service, and what the test-suite runs
  against. Suitable for small deployments and development.
* :class:`~app.events.clickhouse_store.ClickHouseEventStore` — the production
  path, columnar and fast at forensic volumes.

``tests/unit/test_event_store_contract.py`` is written against the interface
and runs against any implementation, so a second backend cannot quietly drift
from the first.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.normalization.schema import NormalizedEvent


@dataclass(slots=True)
class EventQuery:
    """A search/timeline request, independent of any storage engine."""

    tenant_id: str
    case_id: str | None = None
    #: Free-text term. Matched against command lines, paths, names and domains.
    text: str | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    event_types: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    min_severity: int | None = None
    user: str | None = None
    hostname: str | None = None
    ip: str | None = None
    domain: str | None = None
    process: str | None = None
    command_line: str | None = None
    file_hash: str | None = None
    evidence_id: str | None = None
    #: Entity filter for the timeline: matches user, host, process or address.
    entity: str | None = None
    limit: int = 100
    offset: int = 0
    #: Ascending is the natural order for a timeline; search defaults to newest first.
    ascending: bool = False


@dataclass(slots=True)
class EventPage:
    events: list[NormalizedEvent]
    total: int
    limit: int
    offset: int
    took_ms: int = 0
    #: Which backend answered, so the UI can report its real capabilities.
    backend: str = ""


@dataclass(slots=True)
class FieldCount:
    value: str
    count: int


@dataclass(slots=True)
class StoreCapabilities:
    """What a backend can honestly do.

    Surfaced through the search API so an analyst is never left guessing
    whether "no results" means "nothing matched" or "this backend cannot
    express that query".
    """

    name: str
    full_text: bool = False
    fuzzy: bool = False
    wildcard: bool = False
    regex: bool = False
    aggregation: bool = False
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class EventStore(ABC):
    """Normalized event storage and retrieval."""

    name: str

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def ensure_schema(self) -> None:
        """Create tables/indexes if absent. Idempotent."""

    @abstractmethod
    def capabilities(self) -> StoreCapabilities: ...

    @abstractmethod
    async def insert_events(self, events: list[NormalizedEvent]) -> int:
        """Append events. Stores are append-only; corrections are new rows."""

    @abstractmethod
    async def search(self, query: EventQuery) -> EventPage: ...

    @abstractmethod
    async def get_event(self, tenant_id: str, event_id: str) -> NormalizedEvent | None: ...

    @abstractmethod
    async def count_for_case(self, tenant_id: str, case_id: str) -> int: ...

    @abstractmethod
    async def delete_for_evidence(self, tenant_id: str, evidence_id: str) -> int:
        """Remove events derived from one artifact.

        Not a general delete: it exists so a failed or superseded parse can be
        re-run without duplicating events. The raw evidence is untouched, and
        the events are always rebuildable from it.
        """

    @abstractmethod
    async def top_values(
        self, tenant_id: str, case_id: str | None, dimension: str, limit: int = 10
    ) -> list[FieldCount]:
        """Aggregate by a dimension. Computed in the store, never in Python."""

    async def close(self) -> None:
        return None


#: Dimensions ``top_values`` accepts. An allow-list, not string interpolation:
#: the dimension name reaches SQL, so it must never come straight from a caller.
AGGREGATABLE_DIMENSIONS: dict[str, str] = {
    "event_type": "event_type",
    "category": "category",
    "device.hostname": "device_hostname",
    "user.name": "user_name",
    "process.name": "process_name",
    "destination.ip": "dst_ip",
    "destination.domain": "dst_domain",
    "file.sha256": "file_sha256",
}
