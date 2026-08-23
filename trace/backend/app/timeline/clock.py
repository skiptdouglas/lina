"""Clock-skew model (brief §17).

Original timestamps are never overwritten. TRACE stores the observed time, the
offset applied, the corrected time, and how confident the correction is, so an
analyst can always see what the source actually claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class CorrectionMethod(StrEnum):
    NONE = "NONE"
    NTP_REPORTED = "NTP_REPORTED"
    COLLECTOR_DELTA = "COLLECTOR_DELTA"
    CROSS_SOURCE_ANCHOR = "CROSS_SOURCE_ANCHOR"
    ANALYST_ASSERTED = "ANALYST_ASSERTED"


@dataclass(frozen=True, slots=True)
class ClockOffset:
    source: str
    offset_seconds: float
    confidence: float
    method: CorrectionMethod = CorrectionMethod.NONE

    def apply(self, original: datetime) -> datetime:
        return original + timedelta(seconds=self.offset_seconds)


@dataclass(frozen=True, slots=True)
class CorrectedTimestamp:
    original_time: datetime
    corrected_time: datetime
    clock_offset: float
    correction_confidence: float
    method: CorrectionMethod


def correct(original: datetime, offset: ClockOffset | None) -> CorrectedTimestamp:
    if offset is None:
        return CorrectedTimestamp(original, original, 0.0, 1.0, CorrectionMethod.NONE)
    return CorrectedTimestamp(
        original_time=original,
        corrected_time=offset.apply(original),
        clock_offset=offset.offset_seconds,
        correction_confidence=offset.confidence,
        method=offset.method,
    )
