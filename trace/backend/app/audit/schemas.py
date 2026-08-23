"""Audit API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.audit.actions import ActorType, AuditAction


class AuditRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: str
    sequence: int
    timestamp: datetime
    actor: str
    actor_type: ActorType
    action: AuditAction
    case_id: str | None
    evidence_id: str | None
    entity_id: str | None
    source_ip: str | None
    reason: str | None
    details: dict[str, Any]
    prev_hash: str
    record_hash: str


class AuditList(BaseModel):
    items: list[AuditRecordRead]
    total: int
    limit: int
    offset: int


class ChainVerification(BaseModel):
    """Result of recomputing every link in a tenant's chain."""

    verified: bool
    tenant_id: str
    records_checked: int
    first_broken_sequence: int | None = None
    first_broken_audit_id: str | None = None
    missing_sequences: list[int] = []
    detail: str
