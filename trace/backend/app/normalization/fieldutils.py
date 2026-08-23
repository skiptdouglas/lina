"""Small helpers shared by the parsers.

Log formats disagree about almost everything — timestamp shapes, whether a
user is ``DOMAIN\\user`` or two fields, whether a hash bundle is a string or a
map. Normalising that in one place keeps the parsers readable and keeps the
edge cases tested once.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

#: Sysmon's UtcTime and friends: "2026-08-20 08:45:11.123"
_SYSMON_TIME = "%Y-%m-%d %H:%M:%S.%f"
_SYSMON_TIME_NO_MS = "%Y-%m-%d %H:%M:%S"

_HASH_PATTERN = re.compile(r"(?P<algorithm>[A-Za-z0-9]+)=(?P<value>[0-9A-Fa-f]+)")


def parse_timestamp(value: Any) -> datetime | None:
    """Best-effort timestamp parsing across the formats TRACE ingests.

    Returns ``None`` rather than guessing when the value is unusable — an event
    with an invented timestamp is worse than a skipped record.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        # Zeek and Suricata flow records use epoch seconds.
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # Epoch as a string.
    if re.fullmatch(r"\d{9,10}(\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    normalised = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

    for pattern in (_SYSMON_TIME, _SYSMON_TIME_NO_MS):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def split_account(value: Any) -> tuple[str | None, str | None]:
    """``EXAMPLE\\jsmith`` -> ``("EXAMPLE", "jsmith")``.

    Also handles ``jsmith@example.com`` and a bare username. The original
    string is never discarded by the caller — identity resolution needs it
    (brief §14).
    """
    if not value:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    if "\\" in text:
        domain, _, name = text.partition("\\")
        return (domain or None), (name or None)
    if "@" in text:
        name, _, domain = text.partition("@")
        return (domain or None), (name or None)
    return None, text


def parse_hashes(value: Any) -> dict[str, str]:
    """``"SHA256=AB...,MD5=CD..."`` -> ``{"sha256": "ab...", "md5": "cd..."}``.

    Accepts a mapping too, which is what some EVTX exporters emit.
    """
    if not value:
        return {}
    if isinstance(value, dict):
        return {str(k).lower(): str(v).lower() for k, v in value.items() if v}
    return {
        match["algorithm"].lower(): match["value"].lower()
        for match in _HASH_PATTERN.finditer(str(value))
    }


def basename(path: Any) -> str | None:
    """Last path segment of a Windows or POSIX path."""
    if not path:
        return None
    text = str(path).replace("\\", "/").rstrip("/")
    if not text:
        return None
    return text.rsplit("/", 1)[-1] or None


def as_int(value: Any) -> int | None:
    """Integers that may arrive as strings, hex, or empty. ``None`` when absent."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text or text == "-":
        return None
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def as_text(value: Any) -> str | None:
    """Trimmed string, or ``None`` for absent/blank/Zeek's ``-`` placeholder."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    return text


def flatten_windows_event(record: dict[str, Any]) -> dict[str, Any]:
    """Accept both flat and ``{"Event": {"System": …, "EventData": …}}`` shapes.

    ``wevtutil``, ``evtx_dump`` and most SIEM forwarders each pick a different
    one; a parser that only handled its favourite would fail on real exports.
    """
    if "Event" not in record or not isinstance(record["Event"], dict):
        return record

    event = record["Event"]
    flattened: dict[str, Any] = {}
    for section in ("System", "EventData", "UserData"):
        block = event.get(section)
        if isinstance(block, dict):
            for key, value in block.items():
                if key == "Data" and isinstance(value, list):
                    # <Data Name="Image">…</Data> lists
                    for item in value:
                        if isinstance(item, dict) and "Name" in item:
                            flattened[str(item["Name"])] = item.get("#text", item.get("Value"))
                elif isinstance(value, dict) and "#text" in value:
                    flattened[key] = value["#text"]
                else:
                    flattened[key] = value
    # System.EventID may be {"#text": "1"} or nested under Provider.
    for key in ("EventID", "Computer", "TimeCreated"):
        if key in event.get("System", {}) and key not in flattened:
            flattened[key] = event["System"][key]
    if isinstance(flattened.get("TimeCreated"), dict):
        flattened["TimeCreated"] = flattened["TimeCreated"].get("SystemTime")
    return {**record, **flattened}
