"""Pattern Hunter (Sprint 5, brief §21, §22).

Similarity search over events, sequences, process trees, entities, cases and
time ranges. Ranking must be explainable: a match returns *why* it matched, not
only a number.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SubjectKind(StrEnum):
    EVENT = "EVENT"
    SEQUENCE = "SEQUENCE"
    PROCESS_TREE = "PROCESS_TREE"
    ENTITY = "ENTITY"
    CASE = "CASE"
    TIME_RANGE = "TIME_RANGE"


@dataclass(slots=True)
class PatternSubject:
    kind: SubjectKind
    subject_id: str | None = None
    definition: dict | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None


@dataclass(slots=True)
class PatternMatch:
    case: str
    similarity: float
    subject_id: str | None = None
    explanation: str | None = None
    event_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SequenceDefinition:
    """Stored as configuration under ``rules/correlation/`` (brief §22)."""

    sequence_id: str
    steps: list[str]
    within_minutes: int = 30
    scope: str = "HOST"


class PatternHunter(ABC):
    @abstractmethod
    async def find_similar(
        self, subject: PatternSubject, *, tenant_id: str, limit: int = 20
    ) -> list[PatternMatch]: ...

    @abstractmethod
    async def run_sequence(
        self, definition: SequenceDefinition, *, case_id: str, tenant_id: str
    ) -> list[PatternMatch]: ...
