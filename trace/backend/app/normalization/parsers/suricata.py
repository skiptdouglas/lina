"""Suricata EVE JSON parser — alerts, flows, DNS, HTTP and file records.

Suricata's severity runs 1 (most severe) to 3, the inverse of TRACE's 0–10
scale, so it is mapped rather than copied. Getting that backwards would put
the most serious alerts at the bottom of a triage queue.
"""

from __future__ import annotations

from typing import Any

from app.evidence.enums import SourceType
from app.normalization.fieldutils import as_int, as_text, parse_timestamp
from app.normalization.jsonl import RawRecord
from app.normalization.parsers.base import JsonLinesParser, ParseContext
from app.normalization.schema import (
    EventCategory,
    FileRef,
    NetworkEndpoint,
    NetworkRef,
    NormalizedEvent,
)

#: Suricata severity (1 = highest) -> TRACE severity (10 = highest).
SEVERITY_MAP = {1: 9, 2: 7, 3: 5, 4: 3}


class SuricataParser(JsonLinesParser):
    parser_id = "suricata-eve-json"
    handles = (SourceType.SURICATA,)
    supported_records = ("alert", "flow", "netflow", "dns", "http", "tls", "fileinfo")
    description = "Suricata EVE JSON"

    def sniff(self, head: bytes) -> bool:
        sample = head[:8192]
        return b'"event_type"' in sample and (
            b'"alert"' in sample
            or b'"flow_id"' in sample
            or b'"src_ip"' in sample
        )

    def record_kind(self, record: RawRecord) -> str:
        return as_text(record.data.get("event_type")) or "unknown"

    def build_event(self, record: RawRecord, context: ParseContext) -> NormalizedEvent | None:
        data = record.data
        event_type = as_text(data.get("event_type"))
        if event_type not in self.supported_records:
            return None

        timestamp = parse_timestamp(data.get("timestamp"))
        if timestamp is None:
            raise ValueError("Suricata record has no usable 'timestamp'")

        source = NetworkEndpoint(ip=as_text(data.get("src_ip")), port=as_int(data.get("src_port")))
        destination = NetworkEndpoint(
            ip=as_text(data.get("dest_ip")), port=as_int(data.get("dest_port"))
        )
        vendor: dict[str, Any] = {
            "event_type": event_type,
            "flow_id": as_int(data.get("flow_id")),
            "community_id": as_text(data.get("community_id")),
        }
        protocol = as_text(data.get("proto"))

        args = (data, record, context, timestamp, source, destination, vendor, protocol)
        if event_type == "alert":
            return self._alert(*args)
        if event_type in ("flow", "netflow"):
            return self._flow(*args)
        if event_type == "dns":
            return self._dns(*args)
        if event_type == "fileinfo":
            return self._fileinfo(*args)
        return self._generic(*args, event_type)

    def _alert(self, data, record, context, timestamp, source, destination, vendor, protocol):  # noqa: ANN001
        alert = data.get("alert") or {}
        suricata_severity = as_int(alert.get("severity"))
        vendor.update(
            {
                "signature": as_text(alert.get("signature")),
                "signature_id": as_int(alert.get("signature_id")),
                "category": as_text(alert.get("category")),
                "action": as_text(alert.get("action")),
                "suricata_severity": suricata_severity,
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="IDS_ALERT",
            category=EventCategory.ALERT,
            severity=SEVERITY_MAP.get(suricata_severity or 3, 5),
            source=source,
            destination=NetworkEndpoint(
                ip=destination.ip,
                port=destination.port,
                domain=as_text((data.get("http") or {}).get("hostname")),
            ),
            network=NetworkRef(protocol=protocol),
            extra=_clean(vendor),
        )

    def _flow(self, data, record, context, timestamp, source, destination, vendor, protocol):  # noqa: ANN001
        flow = data.get("flow") or data.get("netflow") or {}
        vendor.update({"state": as_text(flow.get("state")), "reason": as_text(flow.get("reason"))})
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="NETWORK_FLOW",
            category=EventCategory.NETWORK,
            severity=2,
            source=source,
            destination=destination,
            network=NetworkRef(
                protocol=protocol,
                direction="outbound",
                bytes_out=as_int(flow.get("bytes_toserver")),
                bytes_in=as_int(flow.get("bytes_toclient")),
                packets=(as_int(flow.get("pkts_toserver")) or 0)
                + (as_int(flow.get("pkts_toclient")) or 0)
                or None,
            ),
            extra=_clean(vendor),
        )

    def _dns(self, data, record, context, timestamp, source, destination, vendor, protocol):  # noqa: ANN001
        dns = data.get("dns") or {}
        vendor.update({"rrtype": as_text(dns.get("rrtype")), "rcode": as_text(dns.get("rcode"))})
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="DNS_QUERY",
            category=EventCategory.DNS,
            severity=2,
            source=source,
            destination=NetworkEndpoint(
                ip=destination.ip, port=destination.port, domain=as_text(dns.get("rrname"))
            ),
            network=NetworkRef(protocol=protocol or "udp"),
            extra=_clean(vendor),
        )

    def _fileinfo(self, data, record, context, timestamp, source, destination, vendor, protocol):  # noqa: ANN001
        fileinfo = data.get("fileinfo") or {}
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="FILE_TRANSFER",
            category=EventCategory.FILE,
            severity=3,
            source=source,
            destination=destination,
            network=NetworkRef(protocol=protocol),
            file=FileRef(
                name=as_text(fileinfo.get("filename")),
                sha256=as_text(fileinfo.get("sha256")),
                md5=as_text(fileinfo.get("md5")),
                size=as_int(fileinfo.get("size")),
            ),
            extra=_clean(vendor),
        )

    def _generic(  # noqa: ANN001, PLR0913
        self, data, record, context, timestamp, source, destination, vendor, protocol, event_type
    ):
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type=f"SURICATA_{event_type.upper()}",
            category=EventCategory.NETWORK,
            severity=2,
            source=source,
            destination=destination,
            network=NetworkRef(protocol=protocol),
            extra=_clean(vendor),
        )


def _clean(vendor: dict[str, Any]) -> dict[str, Any]:
    filtered = {key: value for key, value in vendor.items() if value not in (None, "", [])}
    return {"suricata": filtered} if filtered else {}
