"""Case vocabulary (docs/DATA_MODEL.md §1)."""

from __future__ import annotations

from enum import StrEnum


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CONTAINMENT = "CONTAINMENT"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
