"""The Sprint 2 vertical slice, end to end.

    upload four artifacts -> parse -> normalized events -> search ->
    select a host -> timeline -> click an event -> original bytes ->
    verify the evidence digest -> anchored proof still holds

This is the whole point of normalization: four vendors, four formats, one
chronology — and every event on it can still be walked back to the bytes it
came from and the anchored root those bytes sit under.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import auth

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "scripts" / "generate_demo_data.py"

ARTIFACTS = (
    ("sysmon-operational.jsonl", "SYSMON", "FINANCE-LAPTOP-07"),
    ("windows-security.jsonl", "WINDOWS_SECURITY", "FINANCE-LAPTOP-07"),
    ("zeek-conn.jsonl", "ZEEK", "zeek-sensor-01"),
    ("suricata-eve.jsonl", "SURICATA", "suricata-sensor-01"),
)


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> dict[str, bytes]:
    out = tmp_path_factory.mktemp("sprint2")
    subprocess.run(  # noqa: S603
        [sys.executable, str(GENERATOR), "--out", str(out)],
        capture_output=True, check=True, timeout=120,
    )
    return {p.name: p.read_bytes() for p in out.glob("*.jsonl")}


async def test_from_raw_telemetry_to_a_reconstructed_incident(client, demo) -> None:
    # 1. A case.
    created = await client.post(
        "/api/v1/cases",
        json={"title": "Phishing to exfiltration", "case_id": "CASE-DEMO-001",
              "severity": "CRITICAL"},
        headers=auth(),
    )
    assert created.status_code == 201
    case_id = created.json()["case_id"]

    # 2. Four artifacts from four different vendors.
    uploaded = {}
    for filename, source_type, source in ARTIFACTS:
        response = await client.post(
            "/api/v1/evidence",
            files={"file": (filename, demo[filename], "application/json")},
            data={"case_id": case_id, "source": source, "source_type": source_type,
                  "acquisition_method": "LOG_EXPORT"},
            headers=auth(),
        )
        assert response.status_code == 201, response.text
        uploaded[filename] = response.json()

    # 3. Parse each one. Reads a fresh copy from storage, never the upload.
    total_events = 0
    for filename, evidence in uploaded.items():
        report = await client.post(
            f"/api/v1/ingestion/parse/{evidence['evidence_id']}", json={}, headers=auth()
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["parse_status"] == "PARSED", f"{filename}: {body['detail']}"
        assert body["events_produced"] > 0
        total_events += body["events_produced"]
    assert total_events > 40

    # 4. Search across every source at once.
    powershell = (
        await client.post("/api/v1/search", json={"query": "powershell"}, headers=auth())
    ).json()
    assert powershell["total"] >= 1

    # 5. Pivot to a host and read its story in order.
    timeline = (
        await client.get(
            f"/api/v1/cases/{case_id}/timeline?limit=1000", headers=auth()
        )
    ).json()
    assert timeline["total"] == total_events
    stamps = [entry["event"]["timestamp"] for entry in timeline["entries"]]
    assert stamps == sorted(stamps)

    # All four artifacts contributed to the one chronology.
    assert len({entry["event"]["evidence_id"] for entry in timeline["entries"]}) == 4

    # The intrusion reads as a sequence.
    types = [entry["event"]["event_type"] for entry in timeline["entries"]]
    assert types.index("PROCESS_CREATE") < types.index("PROCESS_ACCESS")
    assert "IDS_ALERT" in types
    assert "LOG_CLEARED" in types, "log clearing must survive normalization"

    # 6. Click an event: get the exact original bytes back.
    interesting = next(
        entry for entry in timeline["entries"] if entry["event"]["event_type"] == "PROCESS_ACCESS"
    )
    record = await client.get(
        f"/api/v1/evidence/{interesting['event']['evidence_id']}/record"
        f"?reference={interesting['event']['raw_reference']}",
        headers=auth(),
    )
    assert record.status_code == 200
    source_record = json.loads(record.content)
    assert source_record["EventID"] == 10
    assert record.content in demo["sysmon-operational.jsonl"]

    # 7. The artifact those bytes came from is still provably intact.
    verification = (
        await client.get(
            f"/api/v1/evidence/{interesting['event']['evidence_id']}/verify", headers=auth()
        )
    ).json()
    assert verification["verified"] is True
    assert verification["result"] == "VERIFIED"

    # 8. And it sits under an anchored, signed Merkle root.
    anchor = await client.post("/api/v1/anchors", json={}, headers=auth())
    assert anchor.status_code == 201
    bundle = (
        await client.get(
            f"/api/v1/evidence/{interesting['event']['evidence_id']}/proof", headers=auth()
        )
    ).json()
    checked = (
        await client.post("/api/v1/anchoring/verify-bundle", json=bundle, headers=auth())
    ).json()
    assert checked["verified"] is True

    # The full chain, in one assertion: event -> record -> evidence -> root.
    assert bundle["manifest"]["body"]["evidence_id"] == interesting["event"]["evidence_id"]
    assert bundle["manifest"]["body"]["sha256"] == verification["expected_hash"]


async def test_parsing_never_consumes_the_only_copy(client, demo) -> None:
    """ADR-0005: parsers read a fresh copy; the artifact stays byte-identical."""
    await client.post(
        "/api/v1/cases", json={"title": "Re-parse", "case_id": "CASE-REPARSE"}, headers=auth()
    )
    payload = demo["sysmon-operational.jsonl"]
    evidence = (
        await client.post(
            "/api/v1/evidence",
            files={"file": ("sysmon.jsonl", payload, "application/json")},
            data={"case_id": "CASE-REPARSE", "source": "H1", "source_type": "SYSMON"},
            headers=auth(),
        )
    ).json()

    for _ in range(3):
        report = await client.post(
            f"/api/v1/ingestion/parse/{evidence['evidence_id']}",
            json={"force": True},
            headers=auth(),
        )
        assert report.status_code == 200

    # Still verifiable, still the same bytes, still exactly one set of events.
    verification = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/verify", headers=auth())
    ).json()
    assert verification["verified"] is True

    downloaded = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/download?reason=integrity+check",
        headers=auth(),
    )
    assert downloaded.content == payload

    timeline = (
        await client.get("/api/v1/cases/CASE-REPARSE/timeline?limit=1000", headers=auth())
    ).json()
    assert timeline["total"] == report.json()["events_produced"]
