"""ADR-0004: unimplemented capabilities return 501, never fabricated data."""

from __future__ import annotations

import pytest

from app.core.capabilities import CAPABILITIES, CAPABILITY_INDEX, not_implemented
from tests.conftest import auth

STUB_REQUESTS: list[tuple[str, str, dict | None]] = [
    ("POST", "/api/v1/search", {"query": "powershell"}),
    ("GET", "/api/v1/cases/CASE-0001/timeline", None),
    ("GET", "/api/v1/cases/CASE-0001/evidence-gaps", None),
    ("GET", "/api/v1/cases/CASE-0001/contradictions", None),
    ("POST", "/api/v1/ingestion/parse/EVD-1", None),
    ("GET", "/api/v1/entities", None),
    ("GET", "/api/v1/entities/USER-00042", None),
    ("GET", "/api/v1/graph/neighbourhood?entity_id=USER-00042", None),
    ("POST", "/api/v1/detections/sigma/run", {"case_id": "CASE-0001"}),
    ("POST", "/api/v1/detections/yara/scan", {"evidence_ids": ["EVD-1"]}),
    ("GET", "/api/v1/detections/mitre/coverage", None),
    ("GET", "/api/v1/hunt/rare", None),
    ("GET", "/api/v1/hunt/first-seen", None),
    ("POST", "/api/v1/patterns/find-similar", {"subject_kind": "ENTITY", "subject_id": "HOST-1"}),
    ("POST", "/api/v1/patterns/sequences/run", {"case_id": "CASE-0001"}),
    ("GET", "/api/v1/baselines/USER/USER-00042", None),
    ("GET", "/api/v1/anomalies", None),
    ("GET", "/api/v1/anomalies/beacons", None),
    ("GET", "/api/v1/anomalies/exfiltration", None),
    ("POST", "/api/v1/ai/investigate", {"case_id": "CASE-0001", "question": "What happened?"}),
    ("POST", "/api/v1/entities/USER-00042/reveal", {"case_id": "CASE-0001", "reason": "court order 42"}),
    ("POST", "/api/v1/reports/generate", {"case_id": "CASE-0001"}),
    ("GET", "/api/v1/threatintel/enrich?indicator=1.2.3.4", None),
]


@pytest.mark.parametrize(("method", "path", "payload"), STUB_REQUESTS)
async def test_stub_returns_the_not_implemented_contract(client, method, path, payload) -> None:
    response = await client.request(method, path, json=payload, headers=auth())
    assert response.status_code == 501, f"{method} {path} -> {response.status_code}"
    body = response.json()
    assert body["status"] == "NOT_IMPLEMENTED"
    assert body["feature"] in CAPABILITY_INDEX
    assert body["planned_sprint"] >= 2
    assert body["reference"].startswith("docs/ROADMAP.md")
    # Nothing that could be mistaken for a result.
    assert not any(key in body for key in ("matches", "hits", "items", "results"))


async def test_capabilities_endpoint_lists_both_halves(client) -> None:
    response = await client.get("/api/v1/capabilities")
    body = response.json()
    implemented = {c["key"] for c in body["implemented"]}
    pending = {c["key"] for c in body["not_implemented"]}
    assert "evidence.ingest" in implemented
    assert "evidence.verify" in implemented
    assert "patterns.find_similar" in pending
    assert "ai.investigate" in pending
    assert implemented.isdisjoint(pending)
    assert implemented | pending == {c.key for c in CAPABILITIES}


def test_not_implemented_refuses_unknown_or_implemented_keys() -> None:
    with pytest.raises(KeyError):
        not_implemented("does.not.exist")
    with pytest.raises(KeyError):
        not_implemented("evidence.ingest")


def test_every_capability_has_a_sprint_and_title() -> None:
    for capability in CAPABILITIES:
        assert capability.title
        assert 1 <= capability.sprint <= 7
        if capability.status == "NOT_IMPLEMENTED":
            assert capability.sprint >= 2
