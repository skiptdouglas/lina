"""Windows Security / System channel parser.

Covers the events that carry an intrusion: logons, explicit-credential use,
privilege assignment, share access, process creation — and 1102, the Security
log being cleared, which is an evidence-destruction signal in its own right and
is emitted at high severity so it cannot be lost in the noise.
"""

from __future__ import annotations

from typing import Any

from app.evidence.enums import SourceType
from app.normalization.fieldutils import (
    as_int,
    as_text,
    basename,
    flatten_windows_event,
    parse_timestamp,
    split_account,
)
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

#: Windows logon types worth naming in a timeline.
LOGON_TYPES = {
    2: "Interactive",
    3: "Network",
    4: "Batch",
    5: "Service",
    7: "Unlock",
    8: "NetworkCleartext",
    9: "NewCredentials",
    10: "RemoteInteractive",
    11: "CachedInteractive",
}


class WindowsSecurityParser(JsonLinesParser):
    parser_id = "windows-security-json"
    handles = (SourceType.WINDOWS_SECURITY, SourceType.WINDOWS_EVTX)
    supported_records = (
        "4624 Logon",
        "4625 FailedLogon",
        "4634 Logoff",
        "4648 ExplicitCredentials",
        "4672 SpecialPrivileges",
        "4688 ProcessCreate",
        "4720 UserCreated",
        "5140 ShareAccess",
        "5145 ShareObjectAccess",
        "1102 SecurityLogCleared",
        "104 SystemLogCleared",
    )
    description = "Windows Security/System channel in JSON lines"

    def sniff(self, head: bytes) -> bool:
        sample = head[:8192].lower()
        return b'"channel"' in sample and b"security" in sample or (
            b'"eventid"' in sample
            and any(m in sample for m in (b"targetusername", b"logontype", b"subjectusername"))
        )

    def record_kind(self, record: RawRecord) -> str:
        return f"EventID {as_int(flatten_windows_event(record.data).get('EventID'))}"

    def build_event(self, record: RawRecord, context: ParseContext) -> NormalizedEvent | None:
        flat = flatten_windows_event(record.data)
        event_id = as_int(flat.get("EventID"))
        if event_id not in _HANDLED:
            return None

        timestamp = parse_timestamp(flat.get("TimeCreated")) or parse_timestamp(
            flat.get("UtcTime")
        )
        if timestamp is None:
            raise ValueError(f"Windows EventID {event_id} has no usable timestamp")

        device = DeviceRef(hostname=as_text(flat.get("Computer")))
        vendor = {"event_id": event_id, "channel": as_text(flat.get("Channel"))}
        record_id = as_int(flat.get("EventRecordID"))
        if record_id is not None:
            vendor["event_record_id"] = record_id

        if event_id in (4624, 4625, 4634):
            return self._logon(flat, record, context, timestamp, device, vendor, event_id)
        if event_id == 4648:
            return self._explicit_credentials(flat, record, context, timestamp, device, vendor)
        if event_id == 4688:
            return self._process_create(flat, record, context, timestamp, device, vendor)
        if event_id in (5140, 5145):
            return self._share_access(flat, record, context, timestamp, device, vendor)
        if event_id in (1102, 104):
            return self._log_cleared(flat, record, context, timestamp, device, vendor)
        return self._privilege(flat, record, context, timestamp, device, vendor)

    # ---- builders ----------------------------------------------------------
    def _logon(self, flat, record, context, timestamp, device, vendor, event_id):  # noqa: ANN001
        logon_type = as_int(flat.get("LogonType"))
        domain = as_text(flat.get("TargetDomainName"))
        name = as_text(flat.get("TargetUserName"))
        if not name:
            domain, name = split_account(flat.get("TargetUserName"))
        failed = event_id == 4625
        vendor.update(
            {
                "logon_type": logon_type,
                "logon_type_name": LOGON_TYPES.get(logon_type or -1),
                "workstation": as_text(flat.get("WorkstationName")),
                "authentication_package": as_text(flat.get("AuthenticationPackageName")),
                "status": as_text(flat.get("Status")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="AUTH_LOGOFF"
            if event_id == 4634
            else ("AUTH_LOGON_FAILED" if failed else "AUTH_LOGON"),
            category=EventCategory.AUTH,
            # Remote interactive logons are the shape lateral movement takes.
            severity=5 if failed else (4 if logon_type in (10, 3) else 2),
            device=device,
            user=UserRef(name=name, domain=domain, sid=as_text(flat.get("TargetUserSid"))),
            source=NetworkEndpoint(
                ip=as_text(flat.get("IpAddress")), port=as_int(flat.get("IpPort"))
            ),
            extra=_clean(vendor),
        )

    def _explicit_credentials(self, flat, record, context, timestamp, device, vendor):  # noqa: ANN001
        vendor.update(
            {
                "subject_user": as_text(flat.get("SubjectUserName")),
                "target_server": as_text(flat.get("TargetServerName")),
                "process_name": as_text(flat.get("ProcessName")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="AUTH_EXPLICIT_CREDENTIALS",
            category=EventCategory.AUTH,
            severity=5,
            device=device,
            user=UserRef(
                name=as_text(flat.get("TargetUserName")),
                domain=as_text(flat.get("TargetDomainName")),
            ),
            process=ProcessRef(
                name=basename(as_text(flat.get("ProcessName"))),
                path=as_text(flat.get("ProcessName")),
            ),
            extra=_clean(vendor),
        )

    def _process_create(self, flat, record, context, timestamp, device, vendor):  # noqa: ANN001
        image = as_text(flat.get("NewProcessName"))
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="PROCESS_CREATE",
            category=EventCategory.PROCESS,
            severity=3,
            device=device,
            user=UserRef(
                name=as_text(flat.get("SubjectUserName")),
                domain=as_text(flat.get("SubjectDomainName")),
            ),
            process=ProcessRef(
                pid=as_int(flat.get("NewProcessId")),
                name=basename(image),
                path=image,
                command_line=as_text(flat.get("CommandLine")),
                parent_pid=as_int(flat.get("ProcessId")),
                parent_name=basename(as_text(flat.get("ParentProcessName"))),
            ),
            extra=_clean(vendor),
        )

    def _share_access(self, flat, record, context, timestamp, device, vendor):  # noqa: ANN001
        share = as_text(flat.get("ShareName"))
        vendor.update(
            {
                "share_name": share,
                "share_local_path": as_text(flat.get("ShareLocalPath")),
                "access_mask": as_text(flat.get("AccessMask")),
                "relative_target_name": as_text(flat.get("RelativeTargetName")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="FILE_SHARE_ACCESS",
            category=EventCategory.FILE,
            severity=4,
            device=device,
            user=UserRef(
                name=as_text(flat.get("SubjectUserName")),
                domain=as_text(flat.get("SubjectDomainName")),
            ),
            source=NetworkEndpoint(ip=as_text(flat.get("IpAddress"))),
            file=FileRef(path=share, name=basename(share)),
            extra=_clean(vendor),
        )

    def _log_cleared(self, flat, record, context, timestamp, device, vendor):  # noqa: ANN001
        """1102/104 — the audit log was cleared.

        Emitted at severity 9. This is both an attacker action and a gap in
        everything that follows it, and evidence-gap detection (Sprint 7)
        keys off exactly this.
        """
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="LOG_CLEARED",
            category=EventCategory.SYSTEM,
            severity=9,
            device=device,
            user=UserRef(
                name=as_text(flat.get("SubjectUserName")),
                domain=as_text(flat.get("SubjectDomainName")),
            ),
            extra=_clean(vendor),
        )

    def _privilege(self, flat, record, context, timestamp, device, vendor):  # noqa: ANN001
        vendor["privileges"] = as_text(flat.get("PrivilegeList"))
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="AUTH_SPECIAL_PRIVILEGES",
            category=EventCategory.AUTH,
            severity=4,
            device=device,
            user=UserRef(
                name=as_text(flat.get("SubjectUserName")),
                domain=as_text(flat.get("SubjectDomainName")),
            ),
            extra=_clean(vendor),
        )


_HANDLED = {4624, 4625, 4634, 4648, 4672, 4688, 4720, 5140, 5145, 1102, 104}


def _clean(vendor: dict[str, Any]) -> dict[str, Any]:
    filtered = {key: value for key, value in vendor.items() if value is not None}
    return {"windows": filtered} if filtered else {}
