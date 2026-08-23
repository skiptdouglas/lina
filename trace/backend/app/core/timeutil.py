"""UTC time helpers.

TRACE stores every timestamp in UTC. Naive datetimes coming back from a
database that does not persist offsets (SQLite) are re-tagged as UTC on read
rather than silently compared against aware values.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat(value: datetime | None) -> str | None:
    aware = ensure_utc(value)
    return aware.isoformat().replace("+00:00", "Z") if aware else None
