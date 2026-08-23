"""Search backend abstraction (OpenSearch today, Elasticsearch tomorrow).

Implemented in Sprint 2 together with normalization — see
docs/ROADMAP.md#sprint-2. The interface is defined now so that route and
service signatures are stable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SearchQuery:
    """A normalized search request (see ``POST /api/v1/search``)."""

    query: str | None = None
    case_id: str | None = None
    tenant_id: str = "default"
    time_from: datetime | None = None
    time_to: datetime | None = None
    user: str | None = None
    hostname: str | None = None
    ip: str | None = None
    domain: str | None = None
    process: str | None = None
    command_line: str | None = None
    file_hash: str | None = None
    event_type: str | None = None
    limit: int = 100
    offset: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    event_id: str
    score: float
    evidence_id: str
    document: dict[str, Any]


class SearchBackend(ABC):
    name: str

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def ensure_indices(self) -> None: ...

    @abstractmethod
    async def index_events(self, events: list[dict[str, Any]]) -> int: ...

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchHit]: ...
