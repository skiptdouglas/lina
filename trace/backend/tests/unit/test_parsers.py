"""Parsers, exercised against the synthetic telemetry TRACE ships.

``scripts/generate_demo_data.py`` produces the artifacts these tests parse, so
the fixtures are the same bytes an analyst would upload — not hand-tuned
samples that only exist to make a parser look good.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.evidence.enums import SourceType
from app.normalization.parsers import ParseContext, registry
from app.normalization.reference import RawReference
from app.normalization.schema import EventCategory
from app.timeline.clock import ClockOffset, CorrectionMethod

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "scripts" / "generate_demo_data.py"


@pytest.fixture(scope="module")
def demo_data(tmp_path_factory) -> dict[str, bytes]:
    out = tmp_path_factory.mktemp("demo")
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(GENERATOR), "--out", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {path.name: path.read_bytes() for path in out.glob("*.jsonl")}


def context(source_type: SourceType, **overrides) -> ParseContext:
    defaults = dict(
        evidence_id="EVD-test",
        case_id="CASE-DEMO-001",
        tenant_id="default",
        source="FINANCE-LAPTOP-07",
        source_type=source_type,
    )
    defaults.update(overrides)
    return ParseContext(**defaults)


async def stream_of(payload: bytes, chunk: int = 512):
    for offset in range(0, len(payload), chunk):
        yield payload[offset : offset + chunk]


async def parse(payload: bytes, source_type: SourceType, **overrides):
    parser = registry.select(source_type, payload[:8192])
    assert parser is not None, f"no parser selected for {source_type}"
    return parser, await parser.parse(stream_of(payload), context(source_type, **overrides))


# --------------------------------------------------------------------------
# Registry dispatch
# --------------------------------------------------------------------------
def test_registry_selects_by_declared_type(demo_data) -> None:
    parser = registry.select(SourceType.SYSMON, demo_data["sysmon-operational.jsonl"][:8192])
    assert parser.parser_id == "sysmon-json"


def test_registry_falls_back_to_content_when_the_label_is_wrong(demo_data) -> None:
    """An analyst mislabelling an upload should not cost the parse."""
    parser = registry.select(SourceType.SYSMON, demo_data["zeek-conn.jsonl"][:8192])
    assert parser.parser_id == "zeek-json"


def test_registry_returns_none_for_an_unhandled_type() -> None:
    assert registry.select(SourceType.PCAP, b"\xd4\xc3\xb2\xa1binary") is None


def test_every_parser_declares_its_records() -> None:
    for parser in registry.all():
        assert parser.parser_id
        assert parser.handles
        assert parser.supported_records
        assert parser.description


# --------------------------------------------------------------------------
# Provenance — the property that makes an event admissible
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("filename", "source_type"),
    [
        ("sysmon-operational.jsonl", SourceType.SYSMON),
        ("windows-security.jsonl", SourceType.WINDOWS_SECURITY),
        ("zeek-conn.jsonl", SourceType.ZEEK),
        ("suricata-eve.jsonl", SourceType.SURICATA),
    ],
)
async def test_every_event_carries_a_locator_that_addresses_its_own_bytes(
    demo_data, filename, source_type
) -> None:
    payload = demo_data[filename]
    _, outcome = await parse(payload, source_type)
    assert outcome.events, f"{filename} produced no events"

    for event in outcome.events:
        assert event.evidence_id == "EVD-test"
        reference = RawReference.parse(event.raw_reference)
        segment = payload[reference.offset : reference.end]
        # The locator must address exactly one well-formed source record.
        record = json.loads(segment)
        assert isinstance(record, dict)
        assert record, "locator addressed an empty record"


@pytest.mark.parametrize(
    ("filename", "source_type"),
    [
        ("sysmon-operational.jsonl", SourceType.SYSMON),
        ("zeek-conn.jsonl", SourceType.ZEEK),
    ],
)
async def test_locators_survive_awkward_chunk_boundaries(demo_data, filename, source_type) -> None:
    payload = demo_data[filename]
    parser = registry.select(source_type, payload[:8192])
    for chunk in (1, 3, 7, 64, 100_000):
        outcome = await parser.parse(
            _chunked(payload, chunk), context(source_type)
        )
        for event in outcome.events:
            reference = RawReference.parse(event.raw_reference)
            json.loads(payload[reference.offset : reference.end])


async def _chunked(payload: bytes, size: int):
    for offset in range(0, len(payload), size):
        yield payload[offset : offset + size]


# --------------------------------------------------------------------------
# Sysmon
# --------------------------------------------------------------------------
async def test_sysmon_covers_the_required_event_ids(demo_data) -> None:
    """Brief §11: events 1, 3, 7, 10, 11, 13 and 22."""
    _, outcome = await parse(demo_data["sysmon-operational.jsonl"], SourceType.SYSMON)
    types = {event.event_type for event in outcome.events}
    assert {
        "PROCESS_CREATE",
        "NETWORK_CONNECT",
        "IMAGE_LOAD",
        "PROCESS_ACCESS",
        "FILE_CREATE",
        "REGISTRY_SET",
        "DNS_QUERY",
    } <= types
    assert outcome.unrecognised == 0


async def test_sysmon_process_create_is_fully_mapped(demo_data) -> None:
    _, outcome = await parse(demo_data["sysmon-operational.jsonl"], SourceType.SYSMON)
    powershell = next(
        e
        for e in outcome.events
        if e.event_type == "PROCESS_CREATE" and e.process.name == "powershell.exe"
    )
    assert powershell.category == EventCategory.PROCESS
    assert powershell.process.pid == 6612
    assert "-enc" in powershell.process.command_line
    assert powershell.process.parent_name == "WINWORD.EXE"
    assert powershell.process.parent_pid == 4820
    assert len(powershell.process.sha256) == 64
    assert powershell.user.domain == "EXAMPLE"
    assert powershell.user.name == "jsmith"
    assert powershell.device.hostname == "FINANCE-LAPTOP-07"
    assert powershell.original_timestamp == datetime(2026, 8, 20, 8, 45, tzinfo=UTC)


async def test_sysmon_lsass_access_is_escalated(demo_data) -> None:
    """Credential access must not sit at the same severity as a file write."""
    _, outcome = await parse(demo_data["sysmon-operational.jsonl"], SourceType.SYSMON)
    access = next(e for e in outcome.events if e.event_type == "PROCESS_ACCESS")
    assert access.extra["sysmon"]["target_image"].endswith("lsass.exe")
    assert access.severity >= 8
    file_create = next(e for e in outcome.events if e.event_type == "FILE_CREATE")
    assert access.severity > file_create.severity


async def test_sysmon_dns_and_network_map_the_destination(demo_data) -> None:
    _, outcome = await parse(demo_data["sysmon-operational.jsonl"], SourceType.SYSMON)
    dns = next(e for e in outcome.events if e.event_type == "DNS_QUERY")
    assert dns.destination.domain == "cdn-update-service.example"

    connect = next(
        e for e in outcome.events if e.event_type == "NETWORK_CONNECT" and e.destination.port == 443
    )
    assert connect.destination.ip == "203.0.113.47"
    assert connect.network.direction == "outbound"
    assert connect.network.protocol == "tcp"


async def test_sysmon_registry_persistence_is_captured(demo_data) -> None:
    _, outcome = await parse(demo_data["sysmon-operational.jsonl"], SourceType.SYSMON)
    registry_set = next(e for e in outcome.events if e.event_type == "REGISTRY_SET")
    assert "CurrentVersion\\Run" in registry_set.extra["sysmon"]["target_object"]
    assert registry_set.extra["sysmon"]["details"].endswith("updater.exe")


async def test_sysmon_accepts_the_nested_evtx_shape() -> None:
    """wevtutil and evtx_dump wrap events differently; both must parse."""
    nested = json.dumps(
        {
            "Event": {
                "System": {"EventID": 1, "Computer": "H1", "TimeCreated": "2026-08-20T08:45:00Z"},
                "EventData": {
                    "Data": [
                        {"Name": "Image", "#text": "C:\\Windows\\cmd.exe"},
                        {"Name": "CommandLine", "#text": "cmd /c whoami"},
                        {"Name": "ProcessId", "#text": "1234"},
                        {"Name": "User", "#text": "EXAMPLE\\jsmith"},
                    ]
                },
            }
        }
    ).encode() + b"\n"
    _, outcome = await parse(nested, SourceType.SYSMON)
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert event.process.name == "cmd.exe"
    assert event.process.pid == 1234
    assert event.user.name == "jsmith"


async def test_sysmon_reports_unrecognised_event_ids() -> None:
    payload = b'{"EventID": 255, "UtcTime": "2026-08-20 08:45:00.000", "Computer": "H1"}\n'
    _, outcome = await parse(payload, SourceType.SYSMON)
    assert outcome.events == []
    assert outcome.unrecognised == 1
    assert outcome.unrecognised_types == {"EventID 255": 1}


# --------------------------------------------------------------------------
# Windows Security
# --------------------------------------------------------------------------
async def test_windows_security_maps_logons_and_share_access(demo_data) -> None:
    _, outcome = await parse(demo_data["windows-security.jsonl"], SourceType.WINDOWS_SECURITY)
    types = {event.event_type for event in outcome.events}
    assert {"AUTH_LOGON", "AUTH_EXPLICIT_CREDENTIALS", "FILE_SHARE_ACCESS", "LOG_CLEARED"} <= types

    remote = next(
        e
        for e in outcome.events
        if e.event_type == "AUTH_LOGON" and e.extra["windows"]["logon_type"] == 10
    )
    assert remote.extra["windows"]["logon_type_name"] == "RemoteInteractive"
    assert remote.user.name == "svc_backup"
    assert remote.source.ip == "10.20.30.55"


async def test_log_clearing_is_high_severity(demo_data) -> None:
    """Clearing the Security log destroys evidence; it must stand out."""
    _, outcome = await parse(demo_data["windows-security.jsonl"], SourceType.WINDOWS_SECURITY)
    cleared = next(e for e in outcome.events if e.event_type == "LOG_CLEARED")
    assert cleared.severity == 9
    assert cleared.category == EventCategory.SYSTEM
    assert cleared.device.hostname == "FS-CORP-02"


# --------------------------------------------------------------------------
# Zeek
# --------------------------------------------------------------------------
async def test_zeek_conn_maps_flows_and_flags_bulk_transfer(demo_data) -> None:
    _, outcome = await parse(demo_data["zeek-conn.jsonl"], SourceType.ZEEK)
    assert outcome.events
    assert all(e.event_type == "NETWORK_FLOW" for e in outcome.events)

    exfil = max(outcome.events, key=lambda e: e.network.bytes_out or 0)
    assert exfil.network.bytes_out > 40_000_000_000
    assert exfil.destination.ip == "198.51.100.22"
    assert exfil.severity >= 6, "a 40GB outbound transfer should not be severity 2"


async def test_zeek_identifies_log_type_by_field_signature() -> None:
    dns_record = json.dumps(
        {"ts": 1787654711.0, "uid": "C1", "id.orig_h": "10.0.0.1", "id.resp_h": "10.0.0.2",
         "query": "evil.example", "qtype_name": "A"}
    ).encode() + b"\n"
    _, outcome = await parse(dns_record, SourceType.ZEEK)
    assert outcome.events[0].event_type == "DNS_QUERY"
    assert outcome.events[0].destination.domain == "evil.example"


async def test_zeek_epoch_timestamps_are_converted() -> None:
    record = json.dumps({"ts": 1787654711.5, "uid": "C1", "id.orig_h": "10.0.0.1",
                         "conn_state": "SF"}).encode() + b"\n"
    _, outcome = await parse(record, SourceType.ZEEK)
    assert outcome.events[0].original_timestamp.tzinfo is not None
    assert outcome.events[0].original_timestamp.year == 2026


# --------------------------------------------------------------------------
# Suricata
# --------------------------------------------------------------------------
async def test_suricata_alerts_map_severity_the_right_way_round(demo_data) -> None:
    """Suricata 1 = most severe; TRACE 10 = most severe. Inverted, not copied."""
    _, outcome = await parse(demo_data["suricata-eve.jsonl"], SourceType.SURICATA)
    alerts = [e for e in outcome.events if e.event_type == "IDS_ALERT"]
    assert alerts

    worst = next(a for a in alerts if a.extra["suricata"]["suricata_severity"] == 1)
    mild = next(a for a in alerts if a.extra["suricata"]["suricata_severity"] == 2)
    assert worst.severity > mild.severity
    assert worst.severity == 9
    assert "MALWARE" in worst.extra["suricata"]["signature"]


async def test_suricata_alert_carries_the_signature_id(demo_data) -> None:
    _, outcome = await parse(demo_data["suricata-eve.jsonl"], SourceType.SURICATA)
    alert = outcome.events[0]
    assert alert.category == EventCategory.ALERT
    assert isinstance(alert.extra["suricata"]["signature_id"], int)
    assert alert.destination.ip


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------
async def test_linux_auditd_execve_maps_to_process_create() -> None:
    payload = json.dumps(
        {"type": "EXECVE", "timestamp": "2026-08-20T09:00:00Z", "hostname": "web-01",
         "auid": "deploy", "exe": "/usr/bin/curl", "pid": 9001, "cmdline": "curl http://x/y"}
    ).encode() + b"\n"
    _, outcome = await parse(payload, SourceType.LINUX_JSON)
    event = outcome.events[0]
    assert event.event_type == "PROCESS_CREATE"
    assert event.process.name == "curl"
    assert event.process.pid == 9001
    assert event.device.hostname == "web-01"
    assert event.user.name == "deploy"


async def test_linux_preserves_unrecognised_fields() -> None:
    payload = json.dumps(
        {"timestamp": "2026-08-20T09:00:00Z", "host": "web-01",
         "message": "something happened", "custom_vendor_field": "keep me"}
    ).encode() + b"\n"
    _, outcome = await parse(payload, SourceType.LINUX_JSON)
    assert outcome.events[0].extra["linux"]["custom_vendor_field"] == "keep me"


async def test_linux_skips_records_with_no_timestamp() -> None:
    """An event with an invented timestamp is worse than a skipped record."""
    payload = b'{"host": "web-01", "message": "no time here"}\n'
    _, outcome = await parse(payload, SourceType.LINUX_JSON)
    assert outcome.events == []
    assert outcome.unrecognised == 1


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------
async def test_malformed_lines_are_counted_not_fatal(demo_data) -> None:
    """One corrupt record must not cost the other 400,000."""
    payload = (
        b'{"EventID": 1, "UtcTime": "2026-08-20 08:45:00.000", "Image": "a.exe"}\n'
        b"{ this is not json\n"
        b"\n"
        b'{"EventID": 1, "UtcTime": "2026-08-20 08:46:00.000", "Image": "b.exe"}\n'
    )
    _, outcome = await parse(payload, SourceType.SYSMON)
    assert len(outcome.events) == 2
    assert outcome.stats.records_skipped == 1


async def test_records_without_a_timestamp_are_reported_as_errors() -> None:
    payload = b'{"EventID": 1, "Image": "a.exe"}\n'
    _, outcome = await parse(payload, SourceType.SYSMON)
    assert outcome.events == []
    assert len(outcome.errors) == 1
    assert "no usable timestamp" in outcome.errors[0]


async def test_read_limits_truncate_rather_than_exhaust_memory() -> None:
    from app.normalization.jsonl import ReadLimits

    payload = b'{"EventID": 1, "UtcTime": "2026-08-20 08:45:00.000", "Image": "a.exe"}\n' * 50
    _, outcome = await parse(
        payload, SourceType.SYSMON, limits=ReadLimits(max_records=10)
    )
    assert len(outcome.events) == 10
    assert outcome.stats.truncated is True
    assert "record limit" in outcome.stats.truncation_reason


async def test_empty_artifact_parses_to_nothing() -> None:
    _, outcome = await parse(b"", SourceType.SYSMON)
    assert outcome.events == []
    assert outcome.stats.records_read == 0


# --------------------------------------------------------------------------
# Clock skew (brief §17)
# --------------------------------------------------------------------------
async def test_clock_correction_never_overwrites_the_original(demo_data) -> None:
    offset = ClockOffset(
        source="FINANCE-LAPTOP-07",
        offset_seconds=-90.0,
        confidence=0.7,
        method=CorrectionMethod.COLLECTOR_DELTA,
    )
    _, outcome = await parse(
        demo_data["sysmon-operational.jsonl"], SourceType.SYSMON, clock_offset=offset
    )
    event = outcome.events[0]
    assert (event.timestamp - event.original_timestamp).total_seconds() == -90.0
    assert event.clock.clock_offset_seconds == -90.0
    assert event.clock.correction_confidence == 0.7
    assert event.clock.method == "COLLECTOR_DELTA"


async def test_without_an_offset_times_are_identical_and_marked_uncorrected(demo_data) -> None:
    _, outcome = await parse(demo_data["sysmon-operational.jsonl"], SourceType.SYSMON)
    event = outcome.events[0]
    assert event.timestamp == event.original_timestamp
    assert event.clock.clock_offset_seconds == 0.0
    assert event.clock.method == "NONE"
