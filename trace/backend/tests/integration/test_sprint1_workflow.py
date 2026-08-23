"""The Sprint 1 vertical slice, end to end (brief §59).

    create CASE-DEMO-001 → upload evidence → SHA-256 generated
    → raw evidence stored → metadata stored → evidence displayed in the case
    → Verify Evidence → hash recalculated → VERIFIED

Every step is asserted, including the chain-of-custody trail it leaves behind.
"""

from __future__ import annotations

import hashlib

from tests.conftest import auth

SYSMON_SAMPLE = (
    b'{"EventID":1,"UtcTime":"2026-08-20 08:45:11.123","Image":'
    b'"C:\\\\Windows\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe",'
    b'"CommandLine":"powershell -enc SQBFAFgA","ParentImage":'
    b'"C:\\\\Program Files\\\\Microsoft Office\\\\root\\\\Office16\\\\WINWORD.EXE",'
    b'"User":"EXAMPLE\\\\jsmith","Computer":"FINANCE-LAPTOP-07"}\n'
) * 40


async def test_case_to_verified_evidence(client) -> None:
    # 1. TRACE is up and reports what it can do.
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    capabilities = (await client.get("/api/v1/capabilities")).json()
    implemented = {c["key"] for c in capabilities["implemented"]}
    assert {"cases.manage", "evidence.ingest", "evidence.verify"} <= implemented

    # 2. Create the case.
    created = await client.post(
        "/api/v1/cases",
        json={
            "title": "Phishing to lateral movement",
            "description": "Synthetic demonstration incident.",
            "severity": "CRITICAL",
            "case_id": "CASE-DEMO-001",
        },
        headers=auth(),
    )
    assert created.status_code == 201
    case_id = created.json()["case_id"]
    assert case_id == "CASE-DEMO-001"

    # 3. Upload forensic evidence.
    upload = await client.post(
        "/api/v1/evidence",
        files={"file": ("sysmon.jsonl", SYSMON_SAMPLE, "application/json")},
        data={
            "case_id": case_id,
            "source": "FINANCE-LAPTOP-07",
            "source_type": "SYSMON",
            "collector": "manual-upload/1.0",
            "acquisition_method": "LOG_EXPORT",
            "original_path": "C:\\Windows\\System32\\winevt\\Logs\\Sysmon.evtx",
        },
        headers=auth(),
    )
    assert upload.status_code == 201, upload.text
    evidence = upload.json()
    evidence_id = evidence["evidence_id"]

    # 4. SHA-256 was generated over exactly the bytes we sent.
    assert evidence["sha256"] == hashlib.sha256(SYSMON_SAMPLE).hexdigest()
    assert evidence["size"] == len(SYSMON_SAMPLE)

    # 5. Raw evidence is in object storage under a TRACE-generated key.
    assert evidence["storage_bucket"]
    assert evidence["storage_key"].startswith(f"default/{case_id}/{evidence_id}/")

    # 6. Metadata is stored and retrievable.
    fetched = (await client.get(f"/api/v1/evidence/{evidence_id}", headers=auth())).json()
    assert fetched["source"] == "FINANCE-LAPTOP-07"
    assert fetched["source_type"] == "SYSMON"
    assert fetched["acquisition_method"] == "LOG_EXPORT"
    assert fetched["collector"] == "manual-upload/1.0"

    # 7. The evidence is displayed in the case.
    listed = (await client.get(f"/api/v1/evidence?case_id={case_id}", headers=auth())).json()
    assert listed["total"] == 1
    assert listed["items"][0]["evidence_id"] == evidence_id

    case_detail = (await client.get(f"/api/v1/cases/{case_id}", headers=auth())).json()
    assert case_detail["counts"]["evidence"] == 1

    # 8. Verify Evidence -> hash recalculated -> VERIFIED.
    verification = (
        await client.get(f"/api/v1/evidence/{evidence_id}/verify", headers=auth())
    ).json()
    assert verification == {
        "verified": True,
        "expected_hash": evidence["sha256"],
        "actual_hash": evidence["sha256"],
        "evidence_id": evidence_id,
        "algorithm": "sha256",
        "size_expected": len(SYSMON_SAMPLE),
        "size_actual": len(SYSMON_SAMPLE),
        "result": "VERIFIED",
        "verified_at": verification["verified_at"],
        "detail": verification["detail"],
    }

    # 9. The whole workflow left an intact chain of custody.
    trail = (await client.get(f"/api/v1/audit?case_id={case_id}", headers=auth())).json()
    actions = [item["action"] for item in trail["items"]]
    assert {"CASE_CREATE", "COLLECT", "STORE", "VERIFY"} <= set(actions)

    chain = (await client.get("/api/v1/audit/verify-chain", headers=auth())).json()
    assert chain["verified"] is True

    # 10. Evidence is stored, hashed and verifiable *before* anything parses
    #     it. That ordering is Sprint 1's guarantee and it still holds: the
    #     artifact is queued, not yet interpreted.
    assert fetched["parse_status"] == "QUEUED"
    assert "not implemented" not in (fetched["parse_detail"] or "").lower()
