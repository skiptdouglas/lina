"""Audit hash chain (ADR-0006).

``record_hash = sha256(canonical_json(record) || "|" || prev_hash)``

Only the fields in :data:`CHAINED_FIELDS` participate, in a fixed order, so
the digest does not depend on column ordering or JSON key insertion order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.timeutil import isoformat

#: The genesis link of every per-tenant chain.
GENESIS_HASH = "0" * 64

CHAINED_FIELDS: tuple[str, ...] = (
    "audit_id",
    "sequence",
    "tenant_id",
    "timestamp",
    "actor",
    "actor_type",
    "action",
    "case_id",
    "evidence_id",
    "entity_id",
    "source_ip",
    "user_agent",
    "reason",
    "details",
)


def canonical_payload(record: Any) -> dict[str, Any]:
    """Extract the chained fields from a model or mapping."""
    getter = record.get if isinstance(record, dict) else lambda k, d=None: getattr(record, k, d)
    payload: dict[str, Any] = {}
    for field in CHAINED_FIELDS:
        value = getter(field)
        if field == "timestamp":
            value = isoformat(value)
        payload[field] = value
    return payload


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_record_hash(record: Any, prev_hash: str) -> str:
    material = f"{canonical_json(canonical_payload(record))}|{prev_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
