"""Graph abstraction (Sprint 3).

Memgraph is the implementation; the interface is Bolt/Cypher-shaped so Neo4j
can be substituted by configuration (brief §54).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GraphNode:
    entity_id: str
    entity_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphRelationship:
    """An edge with no supporting events is an assertion, not evidence.

    Writers reject an empty ``event_ids`` (docs/DATA_MODEL.md §6).
    """

    source_id: str
    target_id: str
    relationship: str
    event_ids: list[str]
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_ids:
            raise ValueError(
                f"Relationship {self.relationship} must reference at least one event."
            )


class GraphClient(ABC):
    name: str

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def upsert_nodes(self, nodes: list[GraphNode]) -> int: ...

    @abstractmethod
    async def upsert_relationships(self, relationships: list[GraphRelationship]) -> int: ...

    @abstractmethod
    async def neighbourhood(
        self, entity_id: str, *, depth: int = 2, limit: int = 500
    ) -> tuple[list[GraphNode], list[GraphRelationship]]: ...

    @abstractmethod
    async def query(self, cypher: str, parameters: dict[str, Any] | None = None) -> list[dict]:
        """Escape hatch for traversals; parameters are always bound, never interpolated."""
