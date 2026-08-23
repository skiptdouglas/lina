"""Relational :class:`~app.events.store.EventStore`.

Correct everywhere, needs no extra service, and is what the test-suite runs
against. Suitable for development and small deployments; a forensic estate at
real volume wants ClickHouse (ADR-0002).

It is honest about its limits: :meth:`capabilities` reports no fuzzy matching
and no regex, and the search API passes that through so an analyst can tell
"nothing matched" from "this backend cannot express that".
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import String, delete, func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.events.mapping import event_to_row, row_to_event
from app.events.models import EventRow
from app.events.store import (
    AGGREGATABLE_DIMENSIONS,
    EventPage,
    EventQuery,
    EventStore,
    FieldCount,
    StoreCapabilities,
)
from app.normalization.schema import NormalizedEvent

#: Columns a free-text term is matched against.
_TEXT_COLUMNS = (
    EventRow.process_command_line,
    EventRow.process_name,
    EventRow.process_path,
    EventRow.file_path,
    EventRow.file_name,
    EventRow.dst_domain,
    EventRow.dst_ip,
    EventRow.src_ip,
    EventRow.user_name,
    EventRow.device_hostname,
    EventRow.event_type,
)

#: Columns an entity filter is matched against.
_ENTITY_COLUMNS = (
    EventRow.user_name,
    EventRow.user_entity_id,
    EventRow.device_hostname,
    EventRow.device_entity_id,
    EventRow.process_name,
    EventRow.src_ip,
    EventRow.dst_ip,
    EventRow.dst_domain,
)


class SqlEventStore(EventStore):
    name = "sql"

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def ping(self) -> bool:
        try:
            async with self._session_factory() as session:
                await session.execute(select(func.count()).select_from(EventRow).limit(1))
            return True
        except Exception:  # noqa: BLE001 - health probe must not raise
            return False

    async def ensure_schema(self) -> None:
        # Tables are created by Database.create_all(); EventRow is registered
        # through app.models.
        return None

    def capabilities(self) -> StoreCapabilities:
        return StoreCapabilities(
            name=self.name,
            full_text=True,
            fuzzy=False,
            wildcard=False,
            regex=False,
            aggregation=True,
            notes=(
                "Substring matching over indexed columns. No fuzzy, wildcard or "
                "regex search — configure OpenSearch or ClickHouse for those."
            ),
        )

    async def insert_events(self, events: list[NormalizedEvent]) -> int:
        if not events:
            return 0
        rows = []
        for event in events:
            row = event_to_row(event)
            row["device_ip"] = row.get("device_ip") or []
            row["extra"] = row.get("extra") or {}
            rows.append(EventRow(**row))
        async with self._session_factory() as session:
            session.add_all(rows)
            await session.commit()
        return len(rows)

    def _apply_filters(self, stmt, query: EventQuery):  # noqa: ANN001, ANN202
        stmt = stmt.where(EventRow.tenant_id == query.tenant_id)
        if query.case_id:
            stmt = stmt.where(EventRow.case_id == query.case_id)
        if query.evidence_id:
            stmt = stmt.where(EventRow.evidence_id == query.evidence_id)
        if query.time_from:
            stmt = stmt.where(EventRow.timestamp >= query.time_from)
        if query.time_to:
            stmt = stmt.where(EventRow.timestamp <= query.time_to)
        if query.event_types:
            stmt = stmt.where(EventRow.event_type.in_(query.event_types))
        if query.categories:
            stmt = stmt.where(EventRow.category.in_(query.categories))
        if query.min_severity is not None:
            stmt = stmt.where(EventRow.severity >= query.min_severity)
        if query.user:
            stmt = stmt.where(EventRow.user_name.ilike(f"%{query.user}%"))
        if query.hostname:
            stmt = stmt.where(EventRow.device_hostname.ilike(f"%{query.hostname}%"))
        if query.ip:
            stmt = stmt.where(
                or_(
                    EventRow.src_ip == query.ip,
                    EventRow.dst_ip == query.ip,
                    EventRow.device_ip.cast(String).ilike(f"%{query.ip}%"),
                )
            )
        if query.domain:
            stmt = stmt.where(EventRow.dst_domain.ilike(f"%{query.domain}%"))
        if query.process:
            stmt = stmt.where(
                or_(
                    EventRow.process_name.ilike(f"%{query.process}%"),
                    EventRow.parent_name.ilike(f"%{query.process}%"),
                )
            )
        if query.command_line:
            stmt = stmt.where(EventRow.process_command_line.ilike(f"%{query.command_line}%"))
        if query.file_hash:
            digest = query.file_hash.lower()
            stmt = stmt.where(
                or_(
                    func.lower(EventRow.file_sha256) == digest,
                    func.lower(EventRow.process_sha256) == digest,
                )
            )
        if query.entity:
            needle = query.entity
            stmt = stmt.where(or_(*(column == needle for column in _ENTITY_COLUMNS)))
        if query.text:
            pattern = f"%{query.text}%"
            stmt = stmt.where(or_(*(column.ilike(pattern) for column in _TEXT_COLUMNS)))
        return stmt

    async def search(self, query: EventQuery) -> EventPage:
        started = time.monotonic()
        order = EventRow.timestamp.asc() if query.ascending else EventRow.timestamp.desc()

        stmt = self._apply_filters(select(EventRow), query)
        stmt = stmt.order_by(order, EventRow.event_id).limit(query.limit).offset(query.offset)
        count_stmt = self._apply_filters(select(func.count()).select_from(EventRow), query)

        async with self._session_factory() as session:
            rows = list((await session.execute(stmt)).scalars().all())
            total = (await session.execute(count_stmt)).scalar_one()

        events = [row_to_event(_row_dict(row)) for row in rows]
        return EventPage(
            events=events,
            total=total,
            limit=query.limit,
            offset=query.offset,
            took_ms=int((time.monotonic() - started) * 1000),
            backend=self.name,
        )

    async def get_event(self, tenant_id: str, event_id: str) -> NormalizedEvent | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(EventRow).where(
                        EventRow.tenant_id == tenant_id, EventRow.event_id == event_id
                    )
                )
            ).scalars().first()
        return row_to_event(_row_dict(row)) if row else None

    async def count_for_case(self, tenant_id: str, case_id: str) -> int:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(EventRow)
                    .where(EventRow.tenant_id == tenant_id, EventRow.case_id == case_id)
                )
            ).scalar_one()

    async def delete_for_evidence(self, tenant_id: str, evidence_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(EventRow).where(
                    EventRow.tenant_id == tenant_id, EventRow.evidence_id == evidence_id
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def top_values(
        self, tenant_id: str, case_id: str | None, dimension: str, limit: int = 10
    ) -> list[FieldCount]:
        column_name = AGGREGATABLE_DIMENSIONS.get(dimension)
        if column_name is None:
            raise ValueError(f"Dimension '{dimension}' is not aggregatable.")
        column = getattr(EventRow, column_name)

        stmt = (
            select(column, func.count().label("n"))
            .where(EventRow.tenant_id == tenant_id, column != "")
            .group_by(column)
            .order_by(func.count().desc())
            .limit(limit)
        )
        if case_id:
            stmt = stmt.where(EventRow.case_id == case_id)
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [FieldCount(value=str(value), count=int(count)) for value, count in rows]


def _row_dict(row: EventRow) -> dict[str, Any]:
    data = {column.name: getattr(row, column.name) for column in EventRow.__table__.columns}
    if isinstance(data.get("extra"), str):
        data["extra"] = json.loads(data["extra"])
    return data
