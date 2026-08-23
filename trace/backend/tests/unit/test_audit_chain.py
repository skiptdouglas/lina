"""Chain of custody: coverage, hash chaining and tamper detection (ADR-0006)."""

from __future__ import annotations

from sqlalchemy import select

from app.audit.hashing import GENESIS_HASH, compute_record_hash
from app.audit.models import AuditRecord
from tests.conftest import AUDITOR_TOKEN, auth, upload_evidence


async def _records(app, tenant: str = "default") -> list[AuditRecord]:
    async with app.state.trace.database.session_factory() as session:
        result = await session.execute(
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant)
            .order_by(AuditRecord.sequence)
        )
        return list(result.scalars().all())


async def test_ingest_writes_collect_store_and_verify_records(client, case, app) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    actions = [
        r.action for r in await _records(app) if r.evidence_id == evidence["evidence_id"]
    ]
    assert actions == ["COLLECT", "STORE", "VERIFY"]


async def test_case_creation_is_audited(client, case, app) -> None:
    records = await _records(app)
    assert records[0].action == "CASE_CREATE"
    assert records[0].case_id == case["case_id"]
    assert records[0].sequence == 1
    assert records[0].prev_hash == GENESIS_HASH


async def test_chain_links_each_record_to_its_predecessor(client, case, app) -> None:
    await upload_evidence(client, case["case_id"])
    records = await _records(app)
    assert len(records) >= 4

    previous = GENESIS_HASH
    for index, record in enumerate(records, start=1):
        assert record.sequence == index
        assert record.prev_hash == previous
        assert record.record_hash == compute_record_hash(record, record.prev_hash)
        previous = record.record_hash


async def test_verify_chain_endpoint_reports_success(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    body = (await client.get("/api/v1/audit/verify-chain", headers=auth(AUDITOR_TOKEN))).json()
    assert body["verified"] is True
    assert body["records_checked"] >= 4
    assert body["first_broken_sequence"] is None


async def test_editing_a_record_breaks_the_chain(client, case, app) -> None:
    await upload_evidence(client, case["case_id"])
    async with app.state.trace.database.session_factory() as session:
        record = (
            await session.execute(
                select(AuditRecord).where(AuditRecord.sequence == 2).limit(1)
            )
        ).scalars().one()
        record.reason = "retroactively invented justification"
        await session.commit()

    body = (await client.get("/api/v1/audit/verify-chain", headers=auth(AUDITOR_TOKEN))).json()
    assert body["verified"] is False
    assert body["first_broken_sequence"] == 2
    assert "content has changed" in body["detail"]


async def test_deleting_a_record_is_detected(client, case, app) -> None:
    await upload_evidence(client, case["case_id"])
    async with app.state.trace.database.session_factory() as session:
        record = (
            await session.execute(
                select(AuditRecord).where(AuditRecord.sequence == 2).limit(1)
            )
        ).scalars().one()
        await session.delete(record)
        await session.commit()

    body = (await client.get("/api/v1/audit/verify-chain", headers=auth(AUDITOR_TOKEN))).json()
    assert body["verified"] is False
    assert 2 in body["missing_sequences"]


async def test_audit_records_are_tenant_scoped(client, case) -> None:
    from tests.conftest import OTHER_TENANT_TOKEN

    mine = (await client.get("/api/v1/audit", headers=auth(AUDITOR_TOKEN))).json()
    theirs = (await client.get("/api/v1/audit", headers=auth(OTHER_TENANT_TOKEN))).json()
    assert mine["total"] >= 1
    assert theirs["total"] == 0


async def test_audit_records_carry_actor_and_context(client, case, app) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    records = [r for r in await _records(app) if r.action == "COLLECT"]
    assert records
    collect = records[0]
    assert collect.actor == "admin@trace.test"
    assert collect.actor_type == "USER"
    assert collect.case_id == case["case_id"]
    assert collect.evidence_id == evidence["evidence_id"]
    assert collect.details["sha256"] == evidence["sha256"]
    assert collect.details["algorithm"] == "sha256"


async def test_there_is_no_api_to_modify_or_delete_audit_records(client, app) -> None:
    """Audit is append-only through the API surface — by absence, not by policy."""
    schema = app.openapi()
    audit_paths = {p: ops for p, ops in schema["paths"].items() if p.startswith("/api/v1/audit")}
    assert audit_paths
    for path, operations in audit_paths.items():
        assert set(operations) <= {"get"}, f"{path} exposes a mutating method"
