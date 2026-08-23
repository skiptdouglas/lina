"""Zeek JSON parser — conn, dns, http and ssl logs.

Zeek writes one log type per file, and the JSON has no field naming the type,
so the parser identifies each record by its field signature. That is more
robust than trusting the filename, which analysts routinely rename.
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


class ZeekParser(JsonLinesParser):
    parser_id = "zeek-json"
    handles = (SourceType.ZEEK,)
    supported_records = ("conn", "dns", "http", "ssl", "files")
    description = "Zeek JSON logs (conn, dns, http, ssl, files)"

    def sniff(self, head: bytes) -> bool:
        sample = head[:8192]
        return b'"id.orig_h"' in sample or (b'"uid"' in sample and b'"ts"' in sample)

    def record_kind(self, record: RawRecord) -> str:
        return _log_type(record.data) or "unknown"

    def build_event(self, record: RawRecord, context: ParseContext) -> NormalizedEvent | None:
        data = record.data
        log_type = _log_type(data)
        if log_type is None:
            return None

        timestamp = parse_timestamp(data.get("ts"))
        if timestamp is None:
            raise ValueError("Zeek record has no usable 'ts'")

        source = NetworkEndpoint(
            ip=as_text(data.get("id.orig_h")), port=as_int(data.get("id.orig_p"))
        )
        destination = NetworkEndpoint(
            ip=as_text(data.get("id.resp_h")), port=as_int(data.get("id.resp_p"))
        )
        vendor: dict[str, Any] = {"log": log_type, "uid": as_text(data.get("uid"))}

        if log_type == "conn":
            return self._conn(data, record, context, timestamp, source, destination, vendor)
        if log_type == "dns":
            return self._dns(data, record, context, timestamp, source, destination, vendor)
        if log_type == "http":
            return self._http(data, record, context, timestamp, source, destination, vendor)
        if log_type == "ssl":
            return self._ssl(data, record, context, timestamp, source, destination, vendor)
        return self._files(data, record, context, timestamp, source, destination, vendor)

    def _conn(self, data, record, context, timestamp, source, destination, vendor):  # noqa: ANN001
        sent = as_int(data.get("orig_bytes")) or 0
        vendor.update(
            {
                "service": as_text(data.get("service")),
                "conn_state": as_text(data.get("conn_state")),
                "duration": data.get("duration"),
                "orig_pkts": as_int(data.get("orig_pkts")),
                "resp_pkts": as_int(data.get("resp_pkts")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="NETWORK_FLOW",
            category=EventCategory.NETWORK,
            # A large outbound transfer is worth surfacing on its own; the
            # exfiltration detectors in Sprint 5 refine this.
            severity=6 if sent > 1_000_000_000 else 2,
            source=source,
            destination=destination,
            network=NetworkRef(
                protocol=as_text(data.get("proto")),
                direction="outbound",
                bytes_out=as_int(data.get("orig_bytes")),
                bytes_in=as_int(data.get("resp_bytes")),
                packets=(as_int(data.get("orig_pkts")) or 0)
                + (as_int(data.get("resp_pkts")) or 0)
                or None,
            ),
            extra=_clean(vendor),
        )

    def _dns(self, data, record, context, timestamp, source, destination, vendor):  # noqa: ANN001
        query = as_text(data.get("query"))
        vendor.update(
            {
                "qtype_name": as_text(data.get("qtype_name")),
                "rcode_name": as_text(data.get("rcode_name")),
                "answers": data.get("answers"),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="DNS_QUERY",
            category=EventCategory.DNS,
            severity=2,
            source=source,
            destination=NetworkEndpoint(
                ip=destination.ip, port=destination.port, domain=query
            ),
            network=NetworkRef(protocol=as_text(data.get("proto")) or "udp"),
            extra=_clean(vendor),
        )

    def _http(self, data, record, context, timestamp, source, destination, vendor):  # noqa: ANN001
        vendor.update(
            {
                "method": as_text(data.get("method")),
                "uri": as_text(data.get("uri")),
                "user_agent": as_text(data.get("user_agent")),
                "status_code": as_int(data.get("status_code")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="HTTP_REQUEST",
            category=EventCategory.NETWORK,
            severity=2,
            source=source,
            destination=NetworkEndpoint(
                ip=destination.ip, port=destination.port, domain=as_text(data.get("host"))
            ),
            network=NetworkRef(
                protocol="tcp",
                direction="outbound",
                bytes_out=as_int(data.get("request_body_len")),
                bytes_in=as_int(data.get("response_body_len")),
            ),
            extra=_clean(vendor),
        )

    def _ssl(self, data, record, context, timestamp, source, destination, vendor):  # noqa: ANN001
        vendor.update(
            {
                "version": as_text(data.get("version")),
                "cipher": as_text(data.get("cipher")),
                "ja3": as_text(data.get("ja3")),
                "validation_status": as_text(data.get("validation_status")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="TLS_SESSION",
            category=EventCategory.NETWORK,
            severity=2,
            source=source,
            destination=NetworkEndpoint(
                ip=destination.ip,
                port=destination.port,
                domain=as_text(data.get("server_name")),
            ),
            network=NetworkRef(protocol="tcp", direction="outbound"),
            extra=_clean(vendor),
        )

    def _files(self, data, record, context, timestamp, source, destination, vendor):  # noqa: ANN001
        vendor.update(
            {
                "source": as_text(data.get("source")),
                "mime_type": as_text(data.get("mime_type")),
            }
        )
        return self.make_event(
            context=context,
            reference=record.reference,
            original_timestamp=timestamp,
            event_type="FILE_TRANSFER",
            category=EventCategory.FILE,
            severity=3,
            source=source,
            destination=destination,
            file=FileRef(
                name=as_text(data.get("filename")),
                sha256=as_text(data.get("sha256")),
                md5=as_text(data.get("md5")),
                size=as_int(data.get("total_bytes")),
            ),
            extra=_clean(vendor),
        )


def _log_type(data: dict[str, Any]) -> str | None:
    """Identify the Zeek log by its field signature."""
    if "query" in data or "qtype_name" in data:
        return "dns"
    if "method" in data and "uri" in data:
        return "http"
    if "server_name" in data or "ja3" in data or "cipher" in data:
        return "ssl"
    if "sha256" in data and "mime_type" in data:
        return "files"
    if "conn_state" in data or "orig_bytes" in data or "id.orig_h" in data:
        return "conn"
    return None


def _clean(vendor: dict[str, Any]) -> dict[str, Any]:
    filtered = {key: value for key, value in vendor.items() if value not in (None, "", [])}
    return {"zeek": filtered} if filtered else {}
