"""Threat intelligence providers (Sprint 7).

Intelligence *enriches* evidence; it never replaces it and never upgrades an
inference into a fact (brief §39).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Indicator:
    kind: str  # IP | DOMAIN | URL | HASH | EMAIL
    value: str


@dataclass(slots=True)
class Enrichment:
    indicator: Indicator
    provider: str
    verdict: str  # MALICIOUS | SUSPICIOUS | BENIGN | UNKNOWN
    confidence: float
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    references: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ThreatIntelProvider(ABC):
    """MISP, OpenCTI and STIX/TAXII implement this."""

    name: str

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def enrich(self, indicator: Indicator) -> Enrichment: ...
