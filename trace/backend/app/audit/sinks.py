"""Audit sinks.

The relational store is the *chain of record*. ClickHouse is a best-effort
append-only mirror for long-term retention and fast querying (ADR-0003).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.analytics import AnalyticsStore
from app.core.timeutil import ensure_utc

logger = logging.getLogger(__name__)

MIRROR_TABLE = "trace.audit_log"
MIRROR_COLUMNS = (
    "audit_id",
    "tenant_id",
    "sequence",
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
    "prev_hash",
    "record_hash",
)


class AuditMirror(ABC):
    """Secondary, non-authoritative destination for audit records."""

    name: str

    @abstractmethod
    async def emit(self, records: list[Any]) -> None: ...


class NullAuditMirror(AuditMirror):
    name = "null"

    async def emit(self, records: list[Any]) -> None:
        return None


class ClickHouseAuditMirror(AuditMirror):
    """Append-only mirror. Failures are logged, never raised.

    A mirror outage must not block an investigation: the authoritative,
    hash-chained copy is already committed in the metadata store.
    """

    name = "clickhouse"

    def __init__(self, analytics: AnalyticsStore) -> None:
        self._analytics = analytics

    async def emit(self, records: list[Any]) -> None:
        if not records:
            return
        import json  # noqa: PLC0415

        rows = [
            [
                r.audit_id,
                r.tenant_id,
                r.sequence,
                ensure_utc(r.timestamp),
                r.actor,
                r.actor_type,
                r.action,
                r.case_id or "",
                r.evidence_id or "",
                r.entity_id or "",
                r.source_ip or "",
                r.user_agent or "",
                r.reason or "",
                json.dumps(r.details, default=str),
                r.prev_hash,
                r.record_hash,
            ]
            for r in records
        ]
        try:
            await self._analytics.insert(MIRROR_TABLE, MIRROR_COLUMNS, rows)
        except Exception as exc:  # noqa: BLE001 - mirror must never break the request
            logger.warning("Audit mirror write failed for %d record(s): %s", len(rows), exc)
