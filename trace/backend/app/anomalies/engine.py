"""Anomaly detection (Sprint 5, brief §26).

Explainable methods first — z-score, robust z-score, percentiles, moving
averages, frequency deviation. Isolation Forest is added *after* those, not
instead of them. Deep models are explicitly out of scope for the first
iterations.

Every anomaly carries a human-readable ``reason``; a score without an
explanation is not analysis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Method(StrEnum):
    ZSCORE = "ZSCORE"
    ROBUST_ZSCORE = "ROBUST_ZSCORE"
    PERCENTILE = "PERCENTILE"
    MOVING_AVERAGE = "MOVING_AVERAGE"
    FREQUENCY_DEVIATION = "FREQUENCY_DEVIATION"
    ISOLATION_FOREST = "ISOLATION_FOREST"


class SubjectType(StrEnum):
    USER = "USER"
    HOST = "HOST"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"


@dataclass(slots=True)
class Baseline:
    """Behaviour profile for a subject (brief §25).

    ``peer_group_id`` models peer analysis (user vs department, host vs server
    group) from the start, even though automatic grouping lands later (§27).
    """

    baseline_id: str
    subject_type: SubjectType
    subject_id: str
    window_days: int = 30
    peer_group_id: str | None = None
    usual_login_hours: list[int] = field(default_factory=list)
    common_hosts: list[str] = field(default_factory=list)
    common_destinations: list[str] = field(default_factory=list)
    common_processes: list[str] = field(default_factory=list)
    event_frequency_per_day: float = 0.0
    median_bytes_out: float = 0.0
    computed_at: datetime | None = None


@dataclass(slots=True)
class Anomaly:
    anomaly: str
    score: float
    reason: str
    method: Method
    subject_type: SubjectType
    subject_id: str
    baseline_id: str | None = None
    event_ids: list[str] = field(default_factory=list)
    observed_at: datetime | None = None


class AnomalyDetector(ABC):
    """One detector per behaviour dimension (volume, timing, destination, ...)."""

    detector_id: str

    @abstractmethod
    async def evaluate(self, baseline: Baseline, window_days: int = 1) -> list[Anomaly]:
        """Compare recent activity against the baseline.

        Implementations push the aggregation into ClickHouse and return only
        the deviations (docs/ARCHITECTURE.md §3).
        """
