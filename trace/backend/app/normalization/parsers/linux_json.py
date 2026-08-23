"""Generic Linux JSON log parser — journald, auditd exports, app logs.

Linux telemetry has no single schema, so this parser maps the field names that
recur across journald, auditd JSON exports and structured application logs, and
preserves everything it does not recognise under ``extra.linux``. Losing an
unrecognised field would be losing evidence.
"""

from __future__ import annotations

from typing import Any

from app.evidence.enums import SourceType
from app.normalization.fieldutils import as_int, as_text, basename, parse_timestamp
from app.normalization.jsonl import RawRecord
from app.normalization.parsers.base import JsonLinesParser, ParseContext
from app.normalization.schema import (
    DeviceRef,
    EventCategory,
    FileRef,
    NetworkEndpoint,
    NormalizedEvent,
    ProcessRef,
    UserRef,
)

_TIMESTAMP_KEYS = ("timestamp", "@timestamp", "ts", "time", "__REALTIME_TIMESTAMP")
_HOST_KEYS = ("host", "hostname", "_HOSTNAME", "host.name")
_USER_KEYS = ("user", "username", "acct", "auid", "_UID", "USER")
_PROCESS_KEYS = ("process", "comm", "exe", "_COMM", "SYSLOG_IDENTIFIER", "program")
_PID_KEYS = ("pid", "_PID", "ppid")
_MESSAGE_KEYS = ("message", "msg", "MESSAGE", "log")

#: auditd record types that map onto TRACE event types.
_AUDIT_TYPES = {
    "EXECVE": ("PROCESS_CREATE", EventCategory.PROCESS, 3),
    "SYSCALL": ("SYSCALL", EventCategory.SYSTEM, 2),
    "USER_LOGIN": ("AUTH_LOGON", EventCategory.AUTH, 3),
    "USER_AUTH": ("AUTH_LOGON", EventCategory.AUTH, 3),
    "USER_CMD": ("PROCESS_CREATE", EventCategory.PROCESS, 4),
    "ADD_USER": ("ACCOUNT_CREATED", EventCategory.AUTH, 6),
    "CRED_ACQ": ("AUTH_CREDENTIAL", EventCategory.AUTH, 3),
}


class LinuxJsonParser(JsonLinesParser):
    parser_id = "linux-json"
    handles = (SourceType.LINUX_JSON, SourceType.LINUX_SYSLOG)
    supported_records = ("journald", "auditd", "generic-json")
    description = "Linux JSON logs (journald, auditd exports, application logs)"

    def sniff(self, head: bytes) -> bool:
        sample = head[:8192]
        return any(
            marker in sample
            for marker in (b'"_SYSTEMD_UNIT"', b'"SYSLOG_IDENTIFIER"', b'"audit_type"', b'"auid"')
        )

    def record_kind(self, record: RawRecord) -> str:
        data = record.data
        return as_text(data.get("type")) or as_text(data.get("audit_type")) or "generic"

    def build_event(self, record: RawRecord, context: ParseContext) -> NormalizedEvent | None:
        data = record.data
        timestamp = None
        for key in _TIMESTAMP_KEYS:
            timestamp = parse_timestamp(data.get(key))
            if timestamp is not None:
                break
        if timestamp is None:
            # Without a timestamp an event cannot be placed on a timeline, and
            # inventing one would be worse than skipping the record.
            return None

        audit_type = as_text(data.get("type")) or as_text(data.get("audit_type"))
        event_type, category, severity = _AUDIT_TYPES.get(
            (audit_type or "").upper(), ("LOG_RECORD", EventCategory.SYSTEM, 1)
        )

        executable = _first(data, _PROCESS_KEYS)
        vendor = {
            key: value
            for key, value in data.items()
            if key not in _TIMESTAMP_KEYS and value not in (None, "")
        }

        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type=event_type,
            category=category,
            severity=severity,
            device=DeviceRef(hostname=_first(data, _HOST_KEYS)),
            user=UserRef(name=_first(data, _USER_KEYS)),
            process=ProcessRef(
                pid=as_int(_first(data, _PID_KEYS)),
                name=basename(executable) or executable,
                path=as_text(data.get("exe")),
                command_line=as_text(data.get("cmdline")) or _first(data, _MESSAGE_KEYS),
            ),
            file=FileRef(path=as_text(data.get("path")), name=basename(data.get("path"))),
            source=NetworkEndpoint(ip=as_text(data.get("addr")) or as_text(data.get("src_ip"))),
            extra={"linux": vendor} if vendor else {},
        )


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = as_text(data.get(key))
        if value:
            return value
    return None
