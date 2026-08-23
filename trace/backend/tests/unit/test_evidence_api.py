"""Evidence ingest, verification and download (brief §7, §8)."""

from __future__ import annotations

import hashlib

from tests.conftest import (
    ANALYST_TOKEN,
    OTHER_TENANT_TOKEN,
    VIEWER_TOKEN,
    auth,
    upload_evidence,
)

PAYLOAD = b'{"EventID": 1, "Image": "C:\\\\Windows\\\\System32\\\\cmd.exe"}\n' * 20
EXPECTED_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


async def test_upload_hashes_stores_and_registers_evidence(client, case, object_store) -> None:
    response = await upload_evidence(
        client, case["case_id"], content=PAYLOAD, filename="sysmon-operational.jsonl"
    )
    assert response.status_code == 201, response.text
    evidence = response.json()

    assert evidence["sha256"] == EXPECTED_SHA256
    assert evidence["size"] == len(PAYLOAD)
    assert evidence["case_id"] == case["case_id"]
    assert evidence["original_filename"] == "sysmon-operational.jsonl"
    assert evidence["storage_key"].startswith(f"default/{case['case_id']}/{evidence['evidence_id']}/")
    # Queued, not parsed: evidence is stored and verifiable before anything
    # interprets it, and TRACE does not claim otherwise.
    assert evidence["parse_status"] == "QUEUED"
    assert "no events have been produced" in evidence["parse_detail"].lower()

    stored = await object_store.stat(evidence["storage_bucket"], evidence["storage_key"])
    assert stored.size == len(PAYLOAD)


async def test_uploaded_bytes_are_stored_verbatim(client, case, object_store) -> None:
    response = await upload_evidence(client, case["case_id"], content=PAYLOAD)
    evidence = response.json()
    collected = b""
    async for chunk in object_store.stream(evidence["storage_bucket"], evidence["storage_key"]):
        collected += chunk
    assert collected == PAYLOAD


async def test_verify_returns_verified_for_intact_evidence(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()
    response = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/verify", headers=auth()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verified"] is True
    assert body["result"] == "VERIFIED"
    assert body["expected_hash"] == EXPECTED_SHA256
    assert body["actual_hash"] == EXPECTED_SHA256
    assert body["algorithm"] == "sha256"
    assert body["size_expected"] == body["size_actual"] == len(PAYLOAD)


async def test_verify_detects_tampering_with_the_stored_object(client, case, object_store) -> None:
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()

    # Simulate someone modifying evidence behind TRACE's back.
    await object_store.put_bytes(
        evidence["storage_bucket"], evidence["storage_key"], PAYLOAD + b"tampered"
    )

    response = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/verify", headers=auth()
    )
    body = response.json()
    assert body["verified"] is False
    assert body["result"] == "MISMATCH"
    assert body["expected_hash"] == EXPECTED_SHA256
    assert body["actual_hash"] != EXPECTED_SHA256
    assert "does NOT match" in body["detail"]

    # The failure is persisted on the evidence record...
    record = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}", headers=auth())
    ).json()
    assert record["last_verification_result"] == "MISMATCH"
    # ...and audited.
    audit = (
        await client.get(
            f"/api/v1/audit?evidence_id={evidence['evidence_id']}&action=VERIFY", headers=auth()
        )
    ).json()
    assert any(item["details"]["result"] == "MISMATCH" for item in audit["items"])


async def test_verify_reports_a_missing_object(client, case, object_store) -> None:
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()
    await object_store.delete(evidence["storage_bucket"], evidence["storage_key"])

    body = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/verify", headers=auth())
    ).json()
    assert body["verified"] is False
    assert body["result"] == "MISSING"
    assert body["actual_hash"] is None


async def test_upload_to_an_unknown_case_is_rejected_and_stores_nothing(
    client, case, object_store
) -> None:
    response = await upload_evidence(client, "CASE-9999", content=PAYLOAD)
    assert response.status_code == 404
    assert object_store._objects == {}  # noqa: SLF001 - asserting no orphan object


async def test_upload_is_rejected_across_a_tenant_boundary(client, case) -> None:
    response = await upload_evidence(client, case["case_id"], token=OTHER_TENANT_TOKEN)
    assert response.status_code == 404


async def test_upload_over_the_size_cap_is_rejected(client, case, object_store) -> None:
    oversized = b"x" * (1024 * 1024 + 1)
    response = await upload_evidence(client, case["case_id"], content=oversized)
    assert response.status_code == 413
    assert object_store._objects == {}  # noqa: SLF001


async def test_empty_upload_is_accepted_and_hashes_the_empty_string(client, case) -> None:
    """A zero-byte artifact is still evidence — of a zero-byte artifact."""
    response = await upload_evidence(client, case["case_id"], content=b"", filename="empty.log")
    assert response.status_code == 201
    assert response.json()["sha256"] == hashlib.sha256(b"").hexdigest()
    assert response.json()["size"] == 0


async def test_filename_traversal_cannot_escape_the_case_prefix(client, case) -> None:
    evidence = (
        await upload_evidence(client, case["case_id"], filename="../../../etc/passwd")
    ).json()
    assert evidence["storage_key"] == (
        f"default/{case['case_id']}/{evidence['evidence_id']}/passwd"
    )
    assert ".." not in evidence["storage_key"]


async def test_listing_is_scoped_to_the_case_and_tenant(client, case) -> None:
    await upload_evidence(client, case["case_id"], content=PAYLOAD)
    listed = (
        await client.get(f"/api/v1/evidence?case_id={case['case_id']}", headers=auth())
    ).json()
    assert listed["total"] == 1

    other = await client.get("/api/v1/evidence", headers=auth(OTHER_TENANT_TOKEN))
    assert other.json()["total"] == 0


async def test_case_evidence_count_reflects_uploads(client, case) -> None:
    await upload_evidence(client, case["case_id"], content=PAYLOAD)
    await upload_evidence(client, case["case_id"], content=b"another artifact")
    detail = (await client.get(f"/api/v1/cases/{case['case_id']}", headers=auth())).json()
    assert detail["counts"]["evidence"] == 2


async def test_download_requires_a_reason_and_returns_original_bytes(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()

    missing_reason = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/download", headers=auth()
    )
    assert missing_reason.status_code == 422

    response = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/download?reason=Court+order+CO-42",
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-trace-sha256"] == EXPECTED_SHA256
    assert "attachment" in response.headers["content-disposition"]

    audit = (
        await client.get(
            f"/api/v1/audit?evidence_id={evidence['evidence_id']}&action=DOWNLOAD",
            headers=auth(),
        )
    ).json()
    assert audit["total"] == 1
    assert audit["items"][0]["reason"] == "Court order CO-42"


async def test_viewer_cannot_upload(client, case) -> None:
    response = await upload_evidence(client, case["case_id"], token=VIEWER_TOKEN)
    assert response.status_code == 403


async def test_analyst_can_verify(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()
    response = await client.get(
        f"/api/v1/evidence/{evidence['evidence_id']}/verify", headers=auth(ANALYST_TOKEN)
    )
    assert response.status_code == 200
    assert response.json()["verified"] is True
