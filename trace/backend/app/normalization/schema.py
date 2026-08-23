"""OCSF-inspired normalized event (docs/DATA_MODEL.md §4).

Deliberately a subset — the full OCSF specification is not implemented in the
first iteration (brief §10). Every event carries provenance: ``evidence_id``
and ``raw_reference`` are required, so a normalized event can always be walked
back to the original bytes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventCategory(StrEnum):
    PROCESS = "PROCESS"
    NETWORK = "NETWORK"
    FILE = "FILE"
    REGISTRY = "REGISTRY"
    AUTH = "AUTH"
    DNS = "DNS"
    EMAIL = "EMAIL"
    ALERT = "ALERT"
    SYSTEM = "SYSTEM"
    OTHER = "OTHER"


class UserRef(BaseModel):
    name: str | None = None
    domain: str | None = None
    sid: str | None = None
    upn: str | None = None
    entity_id: str | None = None


class DeviceRef(BaseModel):
    hostname: str | None = None
    ip: list[str] = []
    os: str | None = None
    entity_id: str | None = None


class NetworkEndpoint(BaseModel):
    ip: str | None = None
    port: int | None = None
    domain: str | None = None
    geo_country: str | None = None


class ProcessRef(BaseModel):
    pid: int | None = None
    guid: str | None = None
    name: str | None = None
    path: str | None = None
    command_line: str | None = None
    sha256: str | None = None
    parent_pid: int | None = None
    parent_guid: str | None = None
    parent_name: str | None = None
    integrity_level: str | None = None


class FileRef(BaseModel):
    name: str | None = None
    path: str | None = None
    sha256: str | None = None
    md5: str | None = None
    size: int | None = None


class NetworkRef(BaseModel):
    protocol: str | None = None
    direction: str | None = None
    bytes_in: int | None = None
    bytes_out: int | None = None
    packets: int | None = None


class ClockCorrection(BaseModel):
    """Timestamps are never overwritten (brief §17)."""

    clock_offset_seconds: float = 0.0
    correction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    method: str = "NONE"


class NormalizedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    #: Normalized (clock-corrected) time used for ordering and analytics.
    timestamp: datetime
    #: Exactly as it appeared in the source. Never modified.
    original_timestamp: datetime
    clock: ClockCorrection = ClockCorrection()

    event_type: str
    category: EventCategory = EventCategory.OTHER
    severity: int = Field(default=0, ge=0, le=10)
    case_id: str
    tenant_id: str

    user: UserRef = UserRef()
    device: DeviceRef = DeviceRef()
    source: NetworkEndpoint = NetworkEndpoint()
    destination: NetworkEndpoint = NetworkEndpoint()
    process: ProcessRef = ProcessRef()
    file: FileRef = FileRef()
    network: NetworkRef = NetworkRef()

    #: Locator of the original record inside the raw object (offset / index).
    raw_reference: str
    #: Provenance — required, never null (docs/ARCHITECTURE.md §7).
    evidence_id: str
    extra: dict[str, Any] = {}
