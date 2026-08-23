"""ClickHouse :class:`~app.events.store.EventStore` — the production path.

Aggregation, filtering and ordering all happen in ClickHouse; Python only
shapes the result (docs/ARCHITECTURE.md §3). Every value reaches the server as
a bound parameter, and the one identifier that varies — the aggregation
dimension — comes from an allow-list, never from a caller.

**Not exercised in CI without a live server.** ``tests/integration/test_clickhouse_store.py``
runs the same contract suite as the SQL store and skips when ClickHouse is
unreachable, so the two backends are held to one standard the moment infra
exists.
"""

# ruff: noqa: S608 - The only values interpolated into these query strings are
# module-level column-name constants and allow-list lookups from
# AGGREGATABLE_DIMENSIONS. Every caller-supplied value is a bound parameter
# ({name:Type}); none reaches the SQL text. `test_top_values_rejects_an_unknown_
# dimension` in the shared contract asserts the allow-list holds.
from __future__ import annotations

import json
import time
from typing import Any

from app.core.analytics import AnalyticsStore
from app.events.mapping import COLUMNS, event_to_row, row_to_event
from app.events.store import (
    AGGREGATABLE_DIMENSIONS,
    EventPage,
    EventQuery,
    EventStore,
    FieldCount,
    StoreCapabilities,
)
from app.normalization.schema import NormalizedEvent

TABLE = "trace.events"

_TEXT_COLUMNS = (
    "process_command_line",
    "process_name",
    "process_path",
    "file_path",
    "file_name",
    "dst_domain",
    "dst_ip",
    "src_ip",
    "user_name",
    "device_hostname",
    "event_type",
)

_ENTITY_COLUMNS = (
    "user_name",
    "user_entity_id",
    "device_hostname",
    "device_entity_id",
    "process_name",
    "src_ip",
    "dst_ip",
    "dst_domain",
)


class ClickHouseEventStore(EventStore):
    name = "clickhouse"

    def __init__(self, analytics: AnalyticsStore) -> None:
        self._analytics = analytics

    async def ping(self) -> bool:
        return await self._analytics.ping()

    async def ensure_schema(self) -> None:
        # DDL lives in deploy/clickhouse/*.sql and is applied at startup.
        return None

    def capabilities(self) -> StoreCapabilities:
        return StoreCapabilities(
            name=self.name,
            full_text=True,
            fuzzy=False,
            wildcard=True,
            regex=True,
            aggregation=True,
            notes=(
                "Columnar scans with token-bloom indexes on command lines. "
                "Fuzzy matching lives in OpenSearch, not here."
            ),
        )

    async def insert_events(self, events: list[NormalizedEvent]) -> int:
        if not events:
            return 0
        rows: list[list[Any]] = []
        for event in events:
            mapped = event_to_row(event)
            row: list[Any] = []
            for column in COLUMNS:
                value = mapped.get(column)
                if column == "device_ip":
                    value = list(value or [])
                elif column == "extra":
                    value = json.dumps(value or {}, sort_keys=True)
                elif value is None:
                    value = _empty_for(column)
                row.append(value)
            rows.append(row)
        await self._analytics.insert(TABLE, COLUMNS, rows)
        return len(rows)

    # ---- query building ----------------------------------------------------
    def _where(self, query: EventQuery) -> tuple[str, dict[str, Any]]:
        clauses = ["tenant_id = {tenant_id:String}"]
        params: dict[str, Any] = {"tenant_id": query.tenant_id}

        def add(clause: str, **values: Any) -> None:
            clauses.append(clause)
            params.update(values)

        if query.case_id:
            add("case_id = {case_id:String}", case_id=query.case_id)
        if query.evidence_id:
            add("evidence_id = {evidence_id:String}", evidence_id=query.evidence_id)
        if query.time_from:
            add("timestamp >= {time_from:DateTime64(3)}", time_from=query.time_from)
        if query.time_to:
            add("timestamp <= {time_to:DateTime64(3)}", time_to=query.time_to)
        if query.event_types:
            add("event_type IN {event_types:Array(String)}", event_types=list(query.event_types))
        if query.categories:
            add("category IN {categories:Array(String)}", categories=list(query.categories))
        if query.min_severity is not None:
            add("severity >= {min_severity:UInt8}", min_severity=query.min_severity)
        if query.user:
            add("user_name ILIKE {user:String}", user=f"%{query.user}%")
        if query.hostname:
            add("device_hostname ILIKE {hostname:String}", hostname=f"%{query.hostname}%")
        if query.ip:
            add(
                "(src_ip = {ip:String} OR dst_ip = {ip:String} OR has(device_ip, {ip:String}))",
                ip=query.ip,
            )
        if query.domain:
            add("dst_domain ILIKE {domain:String}", domain=f"%{query.domain}%")
        if query.process:
            add(
                "(process_name ILIKE {process:String} OR parent_name ILIKE {process:String})",
                process=f"%{query.process}%",
            )
        if query.command_line:
            add(
                "process_command_line ILIKE {command_line:String}",
                command_line=f"%{query.command_line}%",
            )
        if query.file_hash:
            add(
                "(lower(file_sha256) = {file_hash:String} "
                "OR lower(process_sha256) = {file_hash:String})",
                file_hash=query.file_hash.lower(),
            )
        if query.entity:
            joined = " OR ".join(f"{column} = {{entity:String}}" for column in _ENTITY_COLUMNS)
            add(f"({joined})", entity=query.entity)
        if query.text:
            joined = " OR ".join(f"{column} ILIKE {{text:String}}" for column in _TEXT_COLUMNS)
            add(f"({joined})", text=f"%{query.text}%")

        return " AND ".join(clauses), params

    async def search(self, query: EventQuery) -> EventPage:
        started = time.monotonic()
        where, params = self._where(query)
        direction = "ASC" if query.ascending else "DESC"
        column_list = ", ".join(COLUMNS)

        rows = await self._analytics.query(
            f"SELECT {column_list} FROM {TABLE} WHERE {where} "
            f"ORDER BY timestamp {direction}, event_id "
            f"LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}",
            {**params, "limit": query.limit, "offset": query.offset},
        )
        counted = await self._analytics.query(
            f"SELECT count() AS n FROM {TABLE} WHERE {where}", params
        )
        total = int(counted[0]["n"]) if counted else 0

        return EventPage(
            events=[row_to_event(row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
            took_ms=int((time.monotonic() - started) * 1000),
            backend=self.name,
        )

    async def get_event(self, tenant_id: str, event_id: str) -> NormalizedEvent | None:
        rows = await self._analytics.query(
            f"SELECT {', '.join(COLUMNS)} FROM {TABLE} "
            "WHERE tenant_id = {tenant_id:String} AND event_id = {event_id:String} LIMIT 1",
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        return row_to_event(rows[0]) if rows else None

    async def count_for_case(self, tenant_id: str, case_id: str) -> int:
        rows = await self._analytics.query(
            f"SELECT count() AS n FROM {TABLE} "
            "WHERE tenant_id = {tenant_id:String} AND case_id = {case_id:String}",
            {"tenant_id": tenant_id, "case_id": case_id},
        )
        return int(rows[0]["n"]) if rows else 0

    async def delete_for_evidence(self, tenant_id: str, evidence_id: str) -> int:
        """Lightweight delete so a failed parse can be re-run.

        ClickHouse mutations are asynchronous; the row count is reported as -1
        because the engine does not return one synchronously. Callers use this
        for idempotent re-parsing, not for accounting.
        """
        before = await self._analytics.query(
            f"SELECT count() AS n FROM {TABLE} "
            "WHERE tenant_id = {tenant_id:String} AND evidence_id = {evidence_id:String}",
            {"tenant_id": tenant_id, "evidence_id": evidence_id},
        )
        await self._analytics.query(
            f"ALTER TABLE {TABLE} DELETE "
            "WHERE tenant_id = {tenant_id:String} AND evidence_id = {evidence_id:String}",
            {"tenant_id": tenant_id, "evidence_id": evidence_id},
        )
        return int(before[0]["n"]) if before else 0

    async def top_values(
        self, tenant_id: str, case_id: str | None, dimension: str, limit: int = 10
    ) -> list[FieldCount]:
        column = AGGREGATABLE_DIMENSIONS.get(dimension)
        if column is None:
            raise ValueError(f"Dimension '{dimension}' is not aggregatable.")

        clauses = ["tenant_id = {tenant_id:String}", f"{column} != ''"]
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        if case_id:
            clauses.append("case_id = {case_id:String}")
            params["case_id"] = case_id

        rows = await self._analytics.query(
            f"SELECT {column} AS value, count() AS n FROM {TABLE} "
            f"WHERE {' AND '.join(clauses)} "
            f"GROUP BY {column} ORDER BY n DESC LIMIT {{limit:UInt32}}",
            params,
        )
        return [FieldCount(value=str(row["value"]), count=int(row["n"])) for row in rows]


#: Columns that are Nullable in ClickHouse — absence is a distinct fact there.
_NULLABLE_COLUMNS = frozenset(
    {
        "src_port",
        "dst_port",
        "process_pid",
        "parent_pid",
        "file_size",
        "network_bytes_in",
        "network_bytes_out",
    }
)

#: Non-nullable columns and the value that represents "absent".
_NON_NULL_DEFAULTS: dict[str, Any] = {
    "clock_offset": 0.0,
    "correction_confidence": 1.0,
    "severity": 0,
}


def _empty_for(column: str) -> Any:
    if column in _NULLABLE_COLUMNS:
        return None
    return _NON_NULL_DEFAULTS.get(column, "")
