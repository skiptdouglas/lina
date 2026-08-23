"""Column mapping shared by every event store.

Both backends materialise the same hot fields as columns and keep everything
else in an ``extra`` blob. Defining that split **once** is what stops the two
implementations drifting apart — and the split is lossless by construction:
``extra`` holds exactly the remainder of the event after the mapped paths are
removed, so ``row_to_event(event_to_row(e)) == e`` for any event.
``tests/unit/test_event_mapping.py`` asserts that on every field.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.timeutil import ensure_utc
from app.normalization.schema import NormalizedEvent

#: column -> dotted path into the event. Order is the column order used by
#: the ClickHouse inserter, so it must stay stable.
COLUMN_PATHS: tuple[tuple[str, str], ...] = (
    ("event_id", "event_id"),
    ("tenant_id", "tenant_id"),
    ("case_id", "case_id"),
    ("timestamp", "timestamp"),
    ("original_timestamp", "original_timestamp"),
    ("clock_offset", "clock.clock_offset_seconds"),
    ("correction_confidence", "clock.correction_confidence"),
    ("event_type", "event_type"),
    ("category", "category"),
    ("severity", "severity"),
    ("user_name", "user.name"),
    ("user_domain", "user.domain"),
    ("user_sid", "user.sid"),
    ("user_entity_id", "user.entity_id"),
    ("device_hostname", "device.hostname"),
    ("device_ip", "device.ip"),
    ("device_entity_id", "device.entity_id"),
    ("src_ip", "source.ip"),
    ("src_port", "source.port"),
    ("dst_ip", "destination.ip"),
    ("dst_port", "destination.port"),
    ("dst_domain", "destination.domain"),
    ("process_pid", "process.pid"),
    ("process_guid", "process.guid"),
    ("process_name", "process.name"),
    ("process_path", "process.path"),
    ("process_command_line", "process.command_line"),
    ("process_sha256", "process.sha256"),
    ("parent_pid", "process.parent_pid"),
    ("parent_guid", "process.parent_guid"),
    ("parent_name", "process.parent_name"),
    ("file_path", "file.path"),
    ("file_name", "file.name"),
    ("file_sha256", "file.sha256"),
    ("file_size", "file.size"),
    ("network_protocol", "network.protocol"),
    ("network_direction", "network.direction"),
    ("network_bytes_in", "network.bytes_in"),
    ("network_bytes_out", "network.bytes_out"),
    ("evidence_id", "evidence_id"),
    ("raw_reference", "raw_reference"),
)

COLUMNS: tuple[str, ...] = tuple(column for column, _ in COLUMN_PATHS) + ("extra",)

#: Columns whose empty value is "" rather than NULL, so the two backends agree.
_STRING_COLUMNS = frozenset(
    column
    for column, path in COLUMN_PATHS
    if column
    not in {
        "timestamp",
        "original_timestamp",
        "clock_offset",
        "correction_confidence",
        "severity",
        "device_ip",
        "src_port",
        "dst_port",
        "process_pid",
        "parent_pid",
        "file_size",
        "network_bytes_in",
        "network_bytes_out",
    }
)


def _get_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _pop_path(data: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _prune_empty(data: Any) -> Any:
    """Drop empty containers so ``extra`` carries only real leftovers."""
    if isinstance(data, dict):
        cleaned = {k: _prune_empty(v) for k, v in data.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, {}, [])}
    return data


def event_to_row(event: NormalizedEvent) -> dict[str, Any]:
    """Flatten an event into the shared column set plus an ``extra`` remainder."""
    payload = event.model_dump(mode="json")
    # Keep real datetimes for the timestamp columns; both stores want them typed.
    payload["timestamp"] = event.timestamp
    payload["original_timestamp"] = event.original_timestamp

    row: dict[str, Any] = {}
    for column, path in COLUMN_PATHS:
        row[column] = _get_path(payload, path)

    remainder = event.model_dump(mode="json")
    for _, path in COLUMN_PATHS:
        _pop_path(remainder, path)
    row["extra"] = _prune_empty(remainder)
    return row


def row_to_event(row: dict[str, Any]) -> NormalizedEvent:
    """Rebuild an event from a stored row. Inverse of :func:`event_to_row`."""
    payload: dict[str, Any] = {}
    extra = row.get("extra")
    if isinstance(extra, str) and extra:
        extra = json.loads(extra)
    if isinstance(extra, dict):
        payload = json.loads(json.dumps(extra))

    for column, path in COLUMN_PATHS:
        value = row.get(column)
        if value is None:
            continue
        if column in _STRING_COLUMNS and value == "":
            # Both backends normalise "absent string" to "", so treat it as absent.
            continue
        if column == "device_ip":
            if isinstance(value, str):
                value = json.loads(value) if value else []
            if not value:
                continue
        if column in ("timestamp", "original_timestamp"):
            value = ensure_utc(value) if isinstance(value, datetime) else value
        _set_path(payload, path, value)

    payload.setdefault("clock", {})
    return NormalizedEvent.model_validate(payload)
