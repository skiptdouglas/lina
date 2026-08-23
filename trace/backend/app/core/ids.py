"""Identifier construction and validation (docs/DATA_MODEL.md §10)."""

from __future__ import annotations

import re
import uuid

CASE_ID_PATTERN = re.compile(r"^CASE-[A-Z0-9][A-Z0-9-]{2,63}$")
EVIDENCE_ID_PREFIX = "EVD"
EVENT_ID_PREFIX = "EVT"
AUDIT_ID_PREFIX = "AUD"
DETECTION_ID_PREFIX = "DET"


def _new(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def new_evidence_id() -> str:
    return _new(EVIDENCE_ID_PREFIX)


def new_event_id() -> str:
    return _new(EVENT_ID_PREFIX)


def new_audit_id() -> str:
    return _new(AUDIT_ID_PREFIX)


def new_detection_id() -> str:
    return _new(DETECTION_ID_PREFIX)


def format_case_id(number: int) -> str:
    """``42`` -> ``CASE-0042``."""
    return f"CASE-{number:04d}"


def is_valid_case_id(case_id: str) -> bool:
    return bool(CASE_ID_PATTERN.match(case_id))


def format_entity_id(entity_type: str, number: int) -> str:
    """``("USER", 42)`` -> ``USER-00042``."""
    return f"{entity_type.upper()}-{number:05d}"
