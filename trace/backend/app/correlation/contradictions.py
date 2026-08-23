"""Contradiction detection (Sprint 7, brief §38).

When sources disagree — the identity provider records a successful login, the
endpoint records none, and the VPN shows a different origin — TRACE reports
``EVIDENCE_CONFLICT``. It does **not** choose which source is correct: that is
an investigative judgement, and silently picking one destroys the finding.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class ConflictKind(StrEnum):
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"


@dataclass(slots=True)
class ConflictingClaim:
    source: str
    claim: str
    event_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Contradiction:
    kind: ConflictKind
    subject: str
    claims: list[ConflictingClaim]
    detail: str
    #: Deliberately absent: a "resolution" field. TRACE never auto-resolves.


class ContradictionDetector(ABC):
    @abstractmethod
    async def detect(self, case_id: str, tenant_id: str) -> list[Contradiction]: ...
