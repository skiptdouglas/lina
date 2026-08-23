"""Sysmon parser — events 1, 3, 7, 10, 11, 13 and 22 (brief §11).

Accepts the flat JSON shape most forwarders emit and the nested
``{"Event": {"System": …, "EventData": …}}`` shape from ``wevtutil`` and
``evtx_dump``; :func:`flatten_windows_event` reconciles them.

Unmapped Sysmon event IDs are counted and reported rather than dropped
silently — an analyst needs to know the log contained 4,000 records the parser
did not understand.
"""

from __future__ import annotations

from typing import Any

from app.evidence.enums import SourceType
from app.normalization.fieldutils import (
    as_int,
    as_text,
    basename,
    flatten_windows_event,
    parse_hashes,
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
    NetworkRef,
    NormalizedEvent,
    ProcessRef,
    UserRef,
)

#: Processes whose memory being read is a credential-access signal.
_SENSITIVE_TARGETS = ("lsass.exe",)


class SysmonParser(JsonLinesParser):
    parser_id = "sysmon-json"
    handles = (SourceType.SYSMON,)
    supported_records = (
        "1 ProcessCreate",
        "3 NetworkConnect",
        "7 ImageLoad",
        "10 ProcessAccess",
        "11 FileCreate",
        "13 RegistrySet",
        "22 DnsQuery",
    )
    description = "Sysmon operational log in JSON lines"

    def sniff(self, head: bytes) -> bool:
        sample = head[:8192].lower()
        return b"sysmon" in sample or (
            b'"eventid"' in sample
            and any(marker in sample for marker in (b"processguid", b"utctime", b"image"))
        )

    def record_kind(self, record: RawRecord) -> str:
        flat = flatten_windows_event(record.data)
        return f"EventID {as_int(flat.get('EventID'))}"

    def build_event(self, record: RawRecord, context: ParseContext) -> NormalizedEvent | None:
        flat = flatten_windows_event(record.data)
        event_id = as_int(flat.get("EventID"))
        builder = _BUILDERS.get(event_id)
        if builder is None:
            return None

        timestamp = parse_timestamp(flat.get("UtcTime")) or parse_timestamp(
            flat.get("TimeCreated")
        )
        if timestamp is None:
            raise ValueError(f"Sysmon EventID {event_id} has no usable timestamp")

        domain, name = split_account(flat.get("User"))
        common: dict[str, Any] = {
            "device": DeviceRef(hostname=as_text(flat.get("Computer"))),
            "user": UserRef(domain=domain, name=name),
        }
        return builder(self, flat, record, context, timestamp, common)

    # ---- per-event-id builders --------------------------------------------
    def _process_create(self, flat, record, context, timestamp, common):  # noqa: ANN001
        hashes = parse_hashes(flat.get("Hashes"))
        image = as_text(flat.get("Image"))
        parent = as_text(flat.get("ParentImage"))
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="PROCESS_CREATE",
            category=EventCategory.PROCESS,
            severity=3,
            process=ProcessRef(
                pid=as_int(flat.get("ProcessId")),
                guid=as_text(flat.get("ProcessGuid")),
                name=basename(image),
                path=image,
                command_line=as_text(flat.get("CommandLine")),
                sha256=hashes.get("sha256"),
                parent_pid=as_int(flat.get("ParentProcessId")),
                parent_guid=as_text(flat.get("ParentProcessGuid")),
                parent_name=basename(parent),
                integrity_level=as_text(flat.get("IntegrityLevel")),
            ),
            extra=_extras(
                flat,
                {
                    "parent_command_line": "ParentCommandLine",
                    "current_directory": "CurrentDirectory",
                    "logon_id": "LogonId",
                },
                hashes=hashes,
            ),
            **common,
        )

    def _network_connect(self, flat, record, context, timestamp, common):  # noqa: ANN001
        image = as_text(flat.get("Image"))
        initiated = str(flat.get("Initiated", "")).lower() == "true"
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="NETWORK_CONNECT",
            category=EventCategory.NETWORK,
            severity=2,
            process=ProcessRef(
                pid=as_int(flat.get("ProcessId")),
                guid=as_text(flat.get("ProcessGuid")),
                name=basename(image),
                path=image,
            ),
            source=NetworkEndpoint(
                ip=as_text(flat.get("SourceIp")), port=as_int(flat.get("SourcePort"))
            ),
            destination=NetworkEndpoint(
                ip=as_text(flat.get("DestinationIp")),
                port=as_int(flat.get("DestinationPort")),
                domain=as_text(flat.get("DestinationHostname")),
            ),
            network=NetworkRef(
                protocol=as_text(flat.get("Protocol")),
                direction="outbound" if initiated else "inbound",
            ),
            **common,
        )

    def _image_load(self, flat, record, context, timestamp, common):  # noqa: ANN001
        hashes = parse_hashes(flat.get("Hashes"))
        loaded = as_text(flat.get("ImageLoaded"))
        signed = str(flat.get("Signed", "")).lower() == "true"
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="IMAGE_LOAD",
            category=EventCategory.PROCESS,
            # An unsigned module loading from a user-writable path is the
            # reason this event is collected at all.
            severity=4 if not signed else 1,
            process=ProcessRef(
                pid=as_int(flat.get("ProcessId")),
                guid=as_text(flat.get("ProcessGuid")),
                name=basename(as_text(flat.get("Image"))),
                path=as_text(flat.get("Image")),
            ),
            file=FileRef(
                name=basename(loaded), path=loaded, sha256=hashes.get("sha256"),
                md5=hashes.get("md5"),
            ),
            extra=_extras(
                flat,
                {"signed": "Signed", "signature": "Signature",
                 "signature_status": "SignatureStatus"},
                hashes=hashes,
            ),
            **common,
        )

    def _process_access(self, flat, record, context, timestamp, common):  # noqa: ANN001
        source_image = as_text(flat.get("SourceImage"))
        target_image = as_text(flat.get("TargetImage"))
        target_name = (basename(target_image) or "").lower()
        sensitive = any(target_name == marker for marker in _SENSITIVE_TARGETS)
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="PROCESS_ACCESS",
            category=EventCategory.PROCESS,
            severity=8 if sensitive else 3,
            process=ProcessRef(
                pid=as_int(flat.get("SourceProcessId")),
                guid=as_text(flat.get("SourceProcessGuid")),
                name=basename(source_image),
                path=source_image,
            ),
            extra=_extras(
                flat,
                {
                    "target_image": "TargetImage",
                    "target_process_id": "TargetProcessId",
                    "target_process_guid": "TargetProcessGuid",
                    "granted_access": "GrantedAccess",
                    "call_trace": "CallTrace",
                },
            ),
            **common,
        )

    def _file_create(self, flat, record, context, timestamp, common):  # noqa: ANN001
        target = as_text(flat.get("TargetFilename"))
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="FILE_CREATE",
            category=EventCategory.FILE,
            severity=2,
            process=ProcessRef(
                pid=as_int(flat.get("ProcessId")),
                guid=as_text(flat.get("ProcessGuid")),
                name=basename(as_text(flat.get("Image"))),
                path=as_text(flat.get("Image")),
            ),
            file=FileRef(name=basename(target), path=target),
            extra=_extras(flat, {"creation_utc_time": "CreationUtcTime"}),
            **common,
        )

    def _registry_set(self, flat, record, context, timestamp, common):  # noqa: ANN001
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="REGISTRY_SET",
            category=EventCategory.REGISTRY,
            severity=4,
            process=ProcessRef(
                pid=as_int(flat.get("ProcessId")),
                guid=as_text(flat.get("ProcessGuid")),
                name=basename(as_text(flat.get("Image"))),
                path=as_text(flat.get("Image")),
            ),
            extra=_extras(
                flat,
                {
                    "target_object": "TargetObject",
                    "details": "Details",
                    "registry_event_type": "EventType",
                },
            ),
            **common,
        )

    def _dns_query(self, flat, record, context, timestamp, common):  # noqa: ANN001
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="DNS_QUERY",
            category=EventCategory.DNS,
            severity=2,
            process=ProcessRef(
                pid=as_int(flat.get("ProcessId")),
                guid=as_text(flat.get("ProcessGuid")),
                name=basename(as_text(flat.get("Image"))),
                path=as_text(flat.get("Image")),
            ),
            destination=NetworkEndpoint(domain=as_text(flat.get("QueryName"))),
            extra=_extras(
                flat, {"query_status": "QueryStatus", "query_results": "QueryResults"}
            ),
            **common,
        )


_BUILDERS = {
    1: SysmonParser._process_create,
    3: SysmonParser._network_connect,
    7: SysmonParser._image_load,
    10: SysmonParser._process_access,
    11: SysmonParser._file_create,
    13: SysmonParser._registry_set,
    22: SysmonParser._dns_query,
}


def _extras(
    flat: dict[str, Any], mapping: dict[str, str], *, hashes: dict[str, str] | None = None
) -> dict[str, Any]:
    """Carry source-specific fields through without inventing schema for them."""
    vendor = {key: as_text(flat.get(source)) for key, source in mapping.items()}
    vendor = {key: value for key, value in vendor.items() if value is not None}
    if hashes:
        # Preserve every algorithm the source reported, not only sha256.
        extra_hashes = {k: v for k, v in hashes.items() if k not in ("sha256",)}
        if extra_hashes:
            vendor["hashes"] = extra_hashes
    record_id = as_int(flat.get("EventRecordID"))
    if record_id is not None:
        vendor["event_record_id"] = record_id
    return {"sysmon": vendor} if vendor else {}
