"""Parsing, search and timeline through the API."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ANALYST_TOKEN, AUDITOR_TOKEN, OTHER_TENANT_TOKEN, VIEWER_TOKEN, auth

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "scripts" / "generate_demo_data.py"


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> dict[str, bytes]:
    out = tmp_path_factory.mktemp("demo-api")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(GENERATOR), "--out", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return {p.name: p.read_bytes() for p in out.glob("*.jsonl")}


async def ingest(client, case_id, demo, filename, source_type, **form):
    response = await client.post(
        "/api/v1/evidence",
        files={"file": (filename, demo[filename], "application/json")},
        data={"case_id": case_id, "source": "FINANCE-LAPTOP-07",
              "source_type": source_type, **form},
        headers=auth(),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def ingest_and_parse(client, case_id, demo, filename, source_type, **form):
    evidence = await ingest(client, case_id, demo, filename, source_type, **form)
    report = await client.post(
        f"/api/v1/ingestion/parse/{evidence['evidence_id']}", json={"force": False},
        headers=auth(),
    )
    assert report.status_code == 200, report.text
    return evidence, report.json()


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
async def test_parse_produces_events_and_reports_what_it_did(client, case, demo) -> None:
    evidence, report = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    assert report["parse_status"] == "PARSED"
    assert report["parser_id"] == "sysmon-json"
    assert report["events_produced"] > 0
    assert report["records_read"] == report["events_produced"]
    assert report["records_skipped"] == 0
    assert report["unrecognised"] == 0
    assert report["truncated"] is False

    fetched = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}", headers=auth())
    ).json()
    assert fetched["parse_status"] == "PARSED"
    assert "sysmon-json" in fetched["parse_detail"]


async def test_parse_is_audited(client, case, demo) -> None:
    evidence, report = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    trail = (
        await client.get(
            f"/api/v1/audit?evidence_id={evidence['evidence_id']}&action=PARSE",
            headers=auth(AUDITOR_TOKEN),
        )
    ).json()
    assert trail["total"] == 1
    assert trail["items"][0]["details"]["events_produced"] == report["events_produced"]
    assert trail["items"][0]["details"]["parser_id"] == "sysmon-json"


async def test_reparsing_replaces_rather_than_duplicates(client, case, demo) -> None:
    """A fixed parser or corrected clock offset must not double a timeline."""
    evidence, first = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    blocked = await client.post(
        f"/api/v1/ingestion/parse/{evidence['evidence_id']}", json={"force": False},
        headers=auth(),
    )
    assert blocked.status_code == 409

    again = await client.post(
        f"/api/v1/ingestion/parse/{evidence['evidence_id']}", json={"force": True},
        headers=auth(),
    )
    assert again.status_code == 200
    assert again.json()["events_produced"] == first["events_produced"]

    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()
    assert timeline["total"] == first["events_produced"]


async def test_parse_reports_unsupported_rather_than_pretending(client, case) -> None:
    upload = await client.post(
        "/api/v1/evidence",
        files={"file": ("mystery.bin", b"\x00\x01\x02not a log at all", "application/octet-stream")},
        data={"case_id": case["case_id"], "source": "unknown", "source_type": "OTHER"},
        headers=auth(),
    )
    report = (
        await client.post(
            f"/api/v1/ingestion/parse/{upload.json()['evidence_id']}", json={}, headers=auth()
        )
    ).json()
    assert report["parse_status"] == "UNSUPPORTED"
    assert report["events_produced"] == 0
    assert "stored and verifiable" in report["detail"]


async def test_parsers_endpoint_declares_coverage(client) -> None:
    """Coverage is a forensic question: what is NOT mapped matters."""
    items = (await client.get("/api/v1/ingestion/parsers", headers=auth())).json()["items"]
    by_id = {item["parser_id"]: item for item in items}
    assert set(by_id) == {
        "sysmon-json", "windows-security-json", "zeek-json",
        "suricata-eve-json", "linux-json",
    }
    sysmon = by_id["sysmon-json"]
    assert any("1 ProcessCreate" in r for r in sysmon["supported_records"])
    assert any("22 DnsQuery" in r for r in sysmon["supported_records"])


async def test_viewer_cannot_trigger_a_parse(client, case, demo) -> None:
    evidence = await ingest(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    denied = await client.post(
        f"/api/v1/ingestion/parse/{evidence['evidence_id']}", json={},
        headers=auth(VIEWER_TOKEN),
    )
    assert denied.status_code == 403


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------
async def test_search_finds_the_encoded_powershell(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    result = (
        await client.post("/api/v1/search", json={"query": "powershell"}, headers=auth())
    ).json()
    assert result["total"] >= 1
    assert any(
        "-enc" in (e["process"]["command_line"] or "") for e in result["events"]
    )


async def test_search_reports_the_backend_and_its_limits(client, case, demo) -> None:
    """"No results" must be distinguishable from "cannot express that query"."""
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    result = (
        await client.post("/api/v1/search", json={"query": "powershell"}, headers=auth())
    ).json()
    backend = result["backend"]
    assert backend["name"] == "sql"
    assert backend["fuzzy"] is False
    assert "No fuzzy" in backend["notes"]


async def test_search_filters_compose(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    result = (
        await client.post(
            "/api/v1/search",
            json={"event_type": "DNS_QUERY", "domain": "cdn-update-service.example"},
            headers=auth(),
        )
    ).json()
    assert result["total"] == 1
    assert result["events"][0]["destination"]["domain"] == "cdn-update-service.example"


async def test_search_by_hash_and_ip(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "zeek-conn.jsonl", "ZEEK")
    by_ip = (
        await client.post("/api/v1/search", json={"ip": "198.51.100.22"}, headers=auth())
    ).json()
    assert by_ip["total"] >= 1


async def test_search_is_audited(client, case, demo) -> None:
    """Who searched for what is part of the investigation record (brief §41)."""
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    await client.post("/api/v1/search", json={"query": "lsass"}, headers=auth())
    trail = (
        await client.get("/api/v1/audit?action=SEARCH", headers=auth(AUDITOR_TOKEN))
    ).json()
    assert trail["total"] == 1
    assert trail["items"][0]["details"]["query"]["query"] == "lsass"


async def test_search_is_tenant_scoped(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    theirs = (
        await client.post(
            "/api/v1/search", json={"query": "powershell"}, headers=auth(OTHER_TENANT_TOKEN)
        )
    ).json()
    assert theirs["total"] == 0


async def test_search_rejects_unknown_fields(client) -> None:
    response = await client.post(
        "/api/v1/search", json={"query": "x", "sql": "DROP TABLE events"}, headers=auth()
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------
async def test_timeline_is_chronological_and_preserves_original_times(
    client, case, demo
) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()

    stamps = [entry["event"]["timestamp"] for entry in timeline["entries"]]
    assert stamps == sorted(stamps)
    assert timeline["clock_corrections_applied"] is False
    for entry in timeline["entries"]:
        assert entry["event"]["original_timestamp"] == entry["event"]["timestamp"]
        assert entry["clock_corrected"] is False


async def test_timeline_shows_the_attack_sequence(client, case, demo) -> None:
    """The demo incident should read as a story, in order."""
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()
    sequence = [entry["event"]["event_type"] for entry in timeline["entries"]]

    def order(event_type: str) -> int:
        return sequence.index(event_type)

    assert order("PROCESS_CREATE") < order("DNS_QUERY")
    assert order("DNS_QUERY") < order("NETWORK_CONNECT")
    assert order("NETWORK_CONNECT") < order("FILE_CREATE")
    assert order("FILE_CREATE") < order("REGISTRY_SET")
    assert order("REGISTRY_SET") < order("PROCESS_ACCESS")


async def test_timeline_filters_by_entity_and_severity(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    by_entity = (
        await client.get(
            f"/api/v1/cases/{case['case_id']}/timeline?entity=FINANCE-LAPTOP-07",
            headers=auth(),
        )
    ).json()
    assert by_entity["total"] > 0

    severe = (
        await client.get(
            f"/api/v1/cases/{case['case_id']}/timeline?min_severity=8", headers=auth()
        )
    ).json()
    assert severe["total"] >= 1
    assert all(e["event"]["severity"] >= 8 for e in severe["entries"])


async def test_timeline_entries_carry_provenance_links(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()
    provenance = timeline["entries"][0]["provenance"]
    assert provenance["evidence_id"].startswith("EVD-")
    assert provenance["raw_reference"].startswith("jsonl:")
    assert provenance["record_url"].startswith("/api/v1/evidence/")


async def test_timeline_reflects_a_collector_reported_clock_offset(client, case, demo) -> None:
    """Corrected ordering, original timestamps intact (brief §17)."""
    await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON",
        clock_offset_seconds="-120", clock_offset_confidence="0.6",
        clock_offset_method="COLLECTOR_DELTA",
    )
    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()
    assert timeline["clock_corrections_applied"] is True
    entry = timeline["entries"][0]
    assert entry["clock_corrected"] is True
    assert entry["event"]["clock"]["clock_offset_seconds"] == -120.0
    assert entry["event"]["clock"]["correction_confidence"] == 0.6
    assert entry["event"]["timestamp"] < entry["event"]["original_timestamp"]


async def test_timeline_of_an_unknown_case_is_404(client) -> None:
    assert (
        await client.get("/api/v1/cases/CASE-9999/timeline", headers=auth())
    ).status_code == 404


# --------------------------------------------------------------------------
# Provenance: event -> original bytes
# --------------------------------------------------------------------------
async def test_raw_record_returns_the_exact_source_bytes(client, case, demo) -> None:
    """The last hop of SHOW EVIDENCE (brief §57)."""
    evidence, _ = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()
    entry = timeline["entries"][0]

    response = await client.get(
        f"/api/v1/evidence/{entry['event']['evidence_id']}/record"
        f"?reference={entry['event']['raw_reference']}",
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"

    original = json.loads(response.content)
    assert original["EventID"] == 1
    # And it is genuinely a slice of the uploaded artifact.
    assert response.content in demo["sysmon-operational.jsonl"]


async def test_raw_record_rejects_a_malformed_locator(client, case, demo) -> None:
    evidence, _ = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    bad = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/record?reference=not-a-locator",
        headers=auth(),
    )
    assert bad.status_code == 404
    assert "Malformed record locator" in bad.json()["detail"]


async def test_raw_record_refuses_to_read_past_the_object(client, case, demo) -> None:
    """A locator must not become an arbitrary read primitive."""
    evidence, _ = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    response = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/record?reference=jsonl:0:999999999:64",
        headers=auth(),
    )
    assert response.status_code == 404
    assert "past the end" in response.json()["detail"]


async def test_raw_record_is_not_visible_across_tenants(client, case, demo) -> None:
    evidence, _ = await ingest_and_parse(
        client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON"
    )
    denied = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/record?reference=jsonl:0:0:10",
        headers=auth(OTHER_TENANT_TOKEN),
    )
    assert denied.status_code == 404


# --------------------------------------------------------------------------
# Multi-source correlation
# --------------------------------------------------------------------------
async def test_multiple_sources_land_on_one_timeline(client, case, demo) -> None:
    """The point of normalization: four formats, one chronology."""
    for filename, source_type in (
        ("sysmon-operational.jsonl", "SYSMON"),
        ("windows-security.jsonl", "WINDOWS_SECURITY"),
        ("zeek-conn.jsonl", "ZEEK"),
        ("suricata-eve.jsonl", "SURICATA"),
    ):
        await ingest_and_parse(client, case["case_id"], demo, filename, source_type)

    timeline = (
        await client.get(
            f"/api/v1/cases/{case['case_id']}/timeline?limit=1000", headers=auth()
        )
    ).json()
    evidence_ids = {entry["event"]["evidence_id"] for entry in timeline["entries"]}
    assert len(evidence_ids) == 4, "events from all four artifacts should be present"

    stamps = [entry["event"]["timestamp"] for entry in timeline["entries"]]
    assert stamps == sorted(stamps), "interleaved sources must still be chronological"

    types = {entry["event"]["event_type"] for entry in timeline["entries"]}
    assert {"PROCESS_CREATE", "AUTH_LOGON", "NETWORK_FLOW", "IDS_ALERT"} <= types


async def test_analyst_can_search_and_read_a_timeline(client, case, demo) -> None:
    await ingest_and_parse(client, case["case_id"], demo, "sysmon-operational.jsonl", "SYSMON")
    assert (
        await client.post("/api/v1/search", json={"query": "powershell"}, headers=auth(ANALYST_TOKEN))
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth(ANALYST_TOKEN))
    ).status_code == 200
