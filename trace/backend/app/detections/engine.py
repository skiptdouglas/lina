"""Detection engines (Sprint 4).

Sigma rules are compiled to ClickHouse SQL and executed *in* ClickHouse so they
run against historical data at scale (retro-hunt), rather than streaming rows
into Python (docs/ARCHITECTURE.md §3).

YARA/YARA-X scans stored evidence in an isolated, resource-limited worker —
never in the API process (docs/SECURITY.md §5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.detections.mitre import MitreMapping


class RuleType(StrEnum):
    SIGMA = "SIGMA"
    YARA = "YARA"
    CORRELATION = "CORRELATION"
    ANOMALY = "ANOMALY"


@dataclass(slots=True)
class Rule:
    rule_id: str
    rule_type: RuleType
    title: str
    severity: str = "MEDIUM"
    mitre: MitreMapping | None = None
    source_path: str | None = None
    enabled: bool = True


@dataclass(slots=True)
class Detection:
    detection_id: str
    rule: Rule
    case_id: str
    tenant_id: str
    detected_at: datetime
    #: Provenance is mandatory (docs/ARCHITECTURE.md §7).
    event_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.event_ids and not self.evidence_ids:
            raise ValueError("A detection must reference the events or evidence it fired on.")


class DetectionEngine(ABC):
    rule_type: RuleType

    @abstractmethod
    async def load_rules(self, directory: str) -> list[Rule]: ...

    @abstractmethod
    async def run(
        self,
        *,
        case_id: str,
        tenant_id: str,
        rule_ids: list[str] | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> list[Detection]: ...
