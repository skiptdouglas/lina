"""Identity resolution (Sprint 3, brief §14).

``DOMAIN\\jsmith``, ``jsmith``, ``jsmith@example.com`` and an Entra object UUID
all resolve to ``USER-00042``. The original identifier is **never discarded**:
it stays on the event and on the alias row, together with how the link was made
and how confident that link is, so a wrong merge is auditable and reversible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EntityType(StrEnum):
    USER = "USER"
    HOST = "HOST"
    IP = "IP"
    DOMAIN = "DOMAIN"
    PROCESS = "PROCESS"
    FILE = "FILE"
    HASH = "HASH"
    EMAIL = "EMAIL"
    APPLICATION = "APPLICATION"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    CLOUD_ACCOUNT = "CLOUD_ACCOUNT"
    CERTIFICATE = "CERTIFICATE"
    URL = "URL"


class LinkMethod(StrEnum):
    SAME_UPN = "SAME_UPN"
    SAME_SID = "SAME_SID"
    SAME_OBJECT_ID = "SAME_OBJECT_ID"
    DIRECTORY_LOOKUP = "DIRECTORY_LOOKUP"
    NAME_HEURISTIC = "NAME_HEURISTIC"
    ANALYST_ASSERTED = "ANALYST_ASSERTED"


@dataclass(slots=True)
class Alias:
    value: str
    method: LinkMethod
    confidence: float
    first_seen: datetime | None = None
    source_event_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Entity:
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[Alias] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    event_count: int = 0


class IdentityResolver(ABC):
    @abstractmethod
    async def resolve(
        self, entity_type: EntityType, identifier: str, tenant_id: str
    ) -> Entity: ...

    @abstractmethod
    async def merge(self, primary_id: str, secondary_id: str, method: LinkMethod) -> Entity:
        """Merging is recorded and reversible; aliases are preserved on both sides."""
