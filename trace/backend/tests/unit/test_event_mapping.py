"""The column/extra split must be lossless in both directions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.events.mapping import COLUMN_PATHS, COLUMNS, event_to_row, row_to_event
from app.normalization.schema import (
    ClockCorrection,
    DeviceRef,
    EventCategory,
    FileRef,
    NetworkEndpoint,
    NetworkRef,
    NormalizedEvent,
    ProcessRef,
    UserRef,
)


def full_event() -> NormalizedEvent:
    """Every optional field populated, including ones with no column."""
    return NormalizedEvent(
        event_id="EVT-full",
        timestamp=datetime(2026, 8, 20, 8, 45, 11, tzinfo=UTC),
        original_timestamp=datetime(2026, 8, 20, 8, 45, 9, tzinfo=UTC),
        clock=ClockCorrection(
            clock_offset_seconds=2.0, correction_confidence=0.9, method="NTP_REPORTED"
        ),
        event_type="PROCESS_CREATE",
        category=EventCategory.PROCESS,
        severity=7,
        case_id="CASE-DEMO-001",
        tenant_id="default",
        user=UserRef(
            name="jsmith", domain="EXAMPLE", sid="S-1-5-21-1", upn="jsmith@example.com",
            entity_id="USER-00042",
        ),
        device=DeviceRef(
            hostname="FINANCE-LAPTOP-07", ip=["10.20.30.55", "fe80::1"], os="Windows 11",
            entity_id="HOST-0018",
        ),
        source=NetworkEndpoint(ip="10.20.30.55", port=51344, geo_country="GB"),
        destination=NetworkEndpoint(
            ip="203.0.113.47", port=443, domain="cdn.example", geo_country="NL"
        ),
        process=ProcessRef(
            pid=6612, guid="{abc}", name="powershell.exe",
            path="C:\\Windows\\powershell.exe", command_line="powershell -enc SQBF",
            sha256="9b" * 32, parent_pid=4820, parent_guid="{def}",
            parent_name="WINWORD.EXE", integrity_level="Medium",
        ),
        file=FileRef(
            name="updater.exe", path="C:\\Users\\x\\updater.exe", sha256="a" * 64,
            md5="b" * 32, size=91204,
        ),
        network=NetworkRef(
            protocol="tcp", direction="outbound", bytes_in=486112, bytes_out=812, packets=740
        ),
        raw_reference="jsonl:12:4096:312",
        evidence_id="EVD-abc",
        extra={"vendor": {"EventRecordID": 90210}},
    )


def test_round_trip_is_lossless_for_a_fully_populated_event() -> None:
    event = full_event()
    assert row_to_event(event_to_row(event)).model_dump(mode="json") == event.model_dump(
        mode="json"
    )


def test_round_trip_is_lossless_for_a_minimal_event() -> None:
    event = NormalizedEvent(
        event_id="EVT-min",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        original_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        event_type="SYSTEM",
        case_id="CASE-0001",
        tenant_id="default",
        raw_reference="jsonl:0:0:10",
        evidence_id="EVD-x",
    )
    assert row_to_event(event_to_row(event)).model_dump(mode="json") == event.model_dump(
        mode="json"
    )


def test_fields_without_a_column_survive_in_extra() -> None:
    """upn, os, geo, md5, packets and integrity_level have no column."""
    row = event_to_row(full_event())
    extra = row["extra"]
    assert extra["user"]["upn"] == "jsmith@example.com"
    assert extra["device"]["os"] == "Windows 11"
    assert extra["destination"]["geo_country"] == "NL"
    assert extra["file"]["md5"] == "b" * 32
    assert extra["network"]["packets"] == 740
    assert extra["process"]["integrity_level"] == "Medium"
    assert extra["extra"]["vendor"]["EventRecordID"] == 90210


def test_mapped_paths_are_absent_from_extra() -> None:
    """No field is stored twice; the split is a partition, not a copy."""
    extra = event_to_row(full_event())["extra"]
    assert "command_line" not in extra.get("process", {})
    assert "sha256" not in extra.get("file", {})
    assert "event_id" not in extra


def test_extra_is_empty_when_every_field_has_a_column() -> None:
    event = NormalizedEvent(
        event_id="EVT-plain",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        original_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        event_type="SYSTEM",
        case_id="CASE-0001",
        tenant_id="default",
        raw_reference="jsonl:0:0:10",
        evidence_id="EVD-x",
    )
    assert event_to_row(event)["extra"] == {"clock": {"method": "NONE"}}


def test_absent_numerics_stay_absent() -> None:
    """PID 0 and 'no PID' are different facts."""
    event = full_event()
    event.process.parent_pid = None
    event.file.size = None
    restored = row_to_event(event_to_row(event))
    assert restored.process.parent_pid is None
    assert restored.file.size is None


def test_zero_is_preserved_as_zero() -> None:
    event = full_event()
    event.file.size = 0
    event.process.pid = 0
    restored = row_to_event(event_to_row(event))
    assert restored.file.size == 0
    assert restored.process.pid == 0


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_strings_are_normalised_to_absent(blank: str) -> None:
    """Storage treats '' as absent, so '' must never be meaningful."""
    process = ProcessRef(name=blank, command_line="real value")
    assert process.name is None
    assert process.command_line == "real value"


def test_column_set_matches_the_declared_paths() -> None:
    assert COLUMNS == tuple(column for column, _ in COLUMN_PATHS) + ("extra",)
    assert len(set(COLUMNS)) == len(COLUMNS)
