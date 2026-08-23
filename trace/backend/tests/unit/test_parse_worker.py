"""The background parse worker.

``run_once`` is deterministic on purpose: a worker you can only test by
sleeping and hoping is a worker you cannot test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.core.security import Role
from app.evidence.models import Evidence
from app.ingestion.worker import ParseWorker, system_principal
from tests.conftest import auth

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "scripts" / "generate_demo_data.py"


@pytest.fixture(scope="module")
def sysmon_bytes(tmp_path_factory) -> bytes:
    out = tmp_path_factory.mktemp("worker-demo")
    subprocess.run(  # noqa: S603
        [sys.executable, str(GENERATOR), "--out", str(out)],
        capture_output=True, check=True, timeout=120,
    )
    return (out / "sysmon-operational.jsonl").read_bytes()


async def upload(client, case_id: str, payload: bytes, source_type: str = "SYSMON"):
    response = await client.post(
        "/api/v1/evidence",
        files={"file": ("sysmon.jsonl", payload, "application/json")},
        data={"case_id": case_id, "source": "HOST-1", "source_type": source_type},
        headers=auth(),
    )
    assert response.status_code == 201
    return response.json()


def test_system_principal_holds_only_service_rights() -> None:
    """Background work is audited like anyone's, not exempt from authorization."""
    principal = system_principal("default")
    assert principal.roles == frozenset({Role.SERVICE})
    assert principal.has_permission("evidence:create")
    assert not principal.has_permission("identity:reveal")
    assert not principal.has_permission("admin:manage")


async def test_worker_drains_the_queue_and_parses(client, app, case, sysmon_bytes) -> None:
    evidence = await upload(client, case["case_id"], sysmon_bytes)
    state = app.state.trace
    assert await state.queue.depth() == 1

    processed = await ParseWorker(state).run_once()
    assert processed == 1
    assert await state.queue.depth() == 0

    async with state.database.session_factory() as session:
        row = await session.get(Evidence, evidence["evidence_id"])
        assert row.parse_status == "PARSED"
        assert "sysmon-json" in row.parse_detail

    timeline = (
        await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=auth())
    ).json()
    assert timeline["total"] > 0


async def test_worker_on_an_empty_queue_does_nothing(app) -> None:
    assert await ParseWorker(app.state.trace).run_once() == 0


async def test_one_unparseable_artifact_does_not_stall_the_queue(
    client, app, case, sysmon_bytes
) -> None:
    """The failure-isolation property the worker exists to provide."""
    broken = await upload(client, case["case_id"], b"\x00\x01 not a log", "OTHER")
    good = await upload(client, case["case_id"], sysmon_bytes)

    processed = await ParseWorker(app.state.trace).run_once()
    assert processed == 2

    async with app.state.trace.database.session_factory() as session:
        broken_row = await session.get(Evidence, broken["evidence_id"])
        good_row = await session.get(Evidence, good["evidence_id"])

    assert broken_row.parse_status == "UNSUPPORTED"
    assert good_row.parse_status == "PARSED", "a bad artifact must not block the good one"


async def test_worker_records_a_hard_failure_on_the_evidence_row(
    client, app, case, sysmon_bytes, monkeypatch
) -> None:
    """An exception mid-parse must surface in the UI, not vanish into a log."""
    evidence = await upload(client, case["case_id"], sysmon_bytes)
    state = app.state.trace

    async def explode(*args, **kwargs):
        raise RuntimeError("event store is on fire")

    monkeypatch.setattr(state.events, "insert_events", explode)
    assert await ParseWorker(state).run_once() == 1

    async with state.database.session_factory() as session:
        row = await session.get(Evidence, evidence["evidence_id"])
    assert row.parse_status == "FAILED"
    assert "event store is on fire" in row.parse_detail
    assert "raw evidence is untouched" in row.parse_detail


async def test_worker_respects_the_queued_limit(client, app, case, sysmon_bytes) -> None:
    for _ in range(4):
        await upload(client, case["case_id"], sysmon_bytes)
    processed = await ParseWorker(app.state.trace).run_once(limit=2)
    assert processed == 2
    assert await app.state.trace.queue.depth() == 2
