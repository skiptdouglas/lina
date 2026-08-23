"""Anonymous / pseudonymous investigation (Sprint 7, brief §30, §31).

``john.smith@example.com`` → ``USER-0042``; ``FINANCE-LAPTOP-07`` → ``HOST-0018``.

Mappings are stored **separately from analytics data**, behind their own
permission (``identity:reveal``) and, in production, their own encryption key.
Analytics stores hold only the pseudonymous identifier.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PseudonymMapping:
    pseudonym: str
    entity_type: str
    tenant_id: str
    created_at: datetime
    #: The real identifier is never returned by a list operation — only by an
    #: audited, reason-carrying reveal.
    original_identifier: str


class Pseudonymiser(ABC):
    @abstractmethod
    async def pseudonymise(self, entity_type: str, identifier: str, tenant_id: str) -> str: ...

    @abstractmethod
    async def reveal(
        self, pseudonym: str, tenant_id: str, *, case_id: str, reason: str, actor: str
    ) -> str:
        """Return the original identifier. Always writes an IDENTITY_REVEAL record."""
