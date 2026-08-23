"""Anchoring endpoints: log, anchors, proofs, verification."""

from __future__ import annotations

import base64

from app.anchoring.manifest import canonical_json
from app.anchoring.merkle import leaf_hash, verify_inclusion
from app.anchoring.signing import STH_DOMAIN, verify_signature
from tests.conftest import (
    ANALYST_TOKEN,
    AUDITOR_TOKEN,
    INVESTIGATOR_TOKEN,
    OTHER_TENANT_TOKEN,
    VIEWER_TOKEN,
    auth,
    upload_evidence,
)


# --------------------------------------------------------------------------
# Log state
# --------------------------------------------------------------------------
async def test_ingest_appends_a_leaf_to_the_log(client, case) -> None:
    before = (await client.get("/api/v1/anchoring/log", headers=auth())).json()
    assert before["tree_size"] == 0

    evidence = (await upload_evidence(client, case["case_id"])).json()

    after = (await client.get("/api/v1/anchoring/log", headers=auth())).json()
    assert after["tree_size"] == 1
    assert after["root_hash"] != before["root_hash"]
    assert after["unanchored_entries"] == 1

    entries = (await client.get("/api/v1/anchoring/log/entries", headers=auth())).json()
    assert entries["total"] == 1
    assert entries["items"][0]["evidence_id"] == evidence["evidence_id"]
    assert entries["items"][0]["entry_type"] == "EVIDENCE_MANIFEST"
    assert entries["items"][0]["leaf_index"] == 0


async def test_leaf_indexes_are_dense_and_ordered(client, case) -> None:
    for index in range(5):
        await upload_evidence(client, case["case_id"], content=f"artifact-{index}".encode())
    entries = (await client.get("/api/v1/anchoring/log/entries", headers=auth())).json()
    indexes = sorted(item["leaf_index"] for item in entries["items"])
    assert indexes == [0, 1, 2, 3, 4]


async def test_root_changes_with_every_append(client, case) -> None:
    roots = []
    for index in range(4):
        await upload_evidence(client, case["case_id"], content=f"a-{index}".encode())
        roots.append((await client.get("/api/v1/anchoring/log", headers=auth())).json()["root_hash"])
    assert len(set(roots)) == 4


async def test_log_is_isolated_between_tenants(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    theirs = (await client.get("/api/v1/anchoring/log", headers=auth(OTHER_TENANT_TOKEN))).json()
    assert theirs["tree_size"] == 0
    assert theirs["log_id"] == "other-tenant:evidence"


async def test_log_exposes_the_signing_public_key(client) -> None:
    status = (await client.get("/api/v1/anchoring/log", headers=auth())).json()
    assert status["signing_algorithm"] == "ed25519"
    assert len(base64.b64decode(status["public_key_b64"])) == 32
    assert len(status["signing_key_id"]) == 32


# --------------------------------------------------------------------------
# Creating anchors
# --------------------------------------------------------------------------
async def test_anchor_signs_and_records_the_current_root(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    await upload_evidence(client, case["case_id"], content=b"second artifact")

    response = await client.post("/api/v1/anchors", json={}, headers=auth())
    assert response.status_code == 201, response.text
    anchor = response.json()

    assert anchor["tree_size"] == 2
    assert anchor["backend"] == "local"
    assert anchor["independence"] == "SELF_ATTESTED"
    assert anchor["status"] == "CONFIRMED"
    assert anchor["external_ref"].startswith("local:")
    assert len(anchor["root_hash"]) == 64

    status = (await client.get("/api/v1/anchoring/log", headers=auth())).json()
    assert status["last_anchored_size"] == 2
    assert status["unanchored_entries"] == 0


async def test_anchoring_an_empty_log_is_refused(client) -> None:
    response = await client.post("/api/v1/anchors", json={}, headers=auth())
    assert response.status_code == 422
    assert "nothing to anchor" in response.json()["detail"].lower()


async def test_re_anchoring_the_same_size_is_refused_without_force(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    first = await client.post("/api/v1/anchors", json={}, headers=auth())
    assert first.status_code == 201

    duplicate = await client.post("/api/v1/anchors", json={}, headers=auth())
    assert duplicate.status_code == 409

    forced = await client.post("/api/v1/anchors", json={"force": True}, headers=auth())
    assert forced.status_code == 201


async def test_anchors_link_to_their_predecessor(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    first = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()
    await upload_evidence(client, case["case_id"], content=b"more")
    second = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()

    assert first["previous_tree_size"] is None
    assert second["previous_tree_size"] == first["tree_size"]
    assert second["previous_root_hash"] == first["root_hash"]


async def test_anchor_also_checkpoints_the_audit_chain(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    await client.post("/api/v1/anchors", json={"include_audit_checkpoint": True}, headers=auth())
    status = (await client.get("/api/v1/anchoring/log", headers=auth())).json()
    assert status["audit_log_size"] >= 1


async def test_anchor_is_audited(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()
    trail = (await client.get("/api/v1/audit?action=ANCHOR", headers=auth(AUDITOR_TOKEN))).json()
    assert trail["total"] == 1
    assert trail["items"][0]["details"]["anchor_id"] == anchor["anchor_id"]
    assert trail["items"][0]["details"]["root_hash"] == anchor["root_hash"]


async def test_unknown_backend_is_rejected(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    response = await client.post(
        "/api/v1/anchors", json={"backend": "dogecoin"}, headers=auth()
    )
    assert response.status_code == 422
    assert "Unknown anchor backend" in response.json()["detail"]


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
async def test_verify_anchor_checks_root_signature_and_ledger(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()

    result = (
        await client.get(f"/api/v1/anchors/{anchor['anchor_id']}/verify", headers=auth())
    ).json()
    assert result["verified"] is True
    assert result["root_recomputed"] is True
    assert result["signature_valid"] is True
    assert result["independence"] == "SELF_ATTESTED"


async def test_verify_anchor_detects_a_forged_signature(client, case, app) -> None:
    from sqlalchemy import select

    from app.anchoring.models import Anchor

    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()

    async with app.state.trace.database.session_factory() as session:
        row = (await session.execute(select(Anchor))).scalars().one()
        row.signature = base64.b64encode(b"\x00" * 64).decode()
        await session.commit()

    result = (
        await client.get(f"/api/v1/anchors/{anchor['anchor_id']}/verify", headers=auth())
    ).json()
    assert result["verified"] is False
    assert result["signature_valid"] is False
    assert "INVALID" in result["detail"]


async def test_verify_anchor_detects_an_edited_log(client, case, app) -> None:
    """The core attack: rewrite an entry after anchoring it."""
    from sqlalchemy import select

    from app.anchoring.log import reset_root_cache
    from app.anchoring.models import MerkleLeaf

    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()

    async with app.state.trace.database.session_factory() as session:
        # The evidence log only — an anchor also checkpoints the audit log.
        leaf = (
            await session.execute(
                select(MerkleLeaf).where(MerkleLeaf.log_id == "default:evidence")
            )
        ).scalars().one()
        leaf.leaf_hash = leaf_hash(b"a different manifest entirely").hex()
        await session.commit()
    reset_root_cache()

    result = (
        await client.get(f"/api/v1/anchors/{anchor['anchor_id']}/verify", headers=auth())
    ).json()
    assert result["verified"] is False
    assert result["root_recomputed"] is False
    assert "does NOT match" in result["detail"]


async def test_local_ledger_tampering_is_detected(client, case, app) -> None:
    from sqlalchemy import select

    from app.anchoring.models import LedgerEntry

    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()

    async with app.state.trace.database.session_factory() as session:
        entry = (await session.execute(select(LedgerEntry))).scalars().one()
        entry.root_hash = "f" * 64
        await session.commit()

    result = (
        await client.get(f"/api/v1/anchors/{anchor['anchor_id']}/verify", headers=auth())
    ).json()
    assert result["verified"] is False
    assert "different root hash" in result["detail"]


# --------------------------------------------------------------------------
# Consistency — the append-only guarantee end to end
# --------------------------------------------------------------------------
async def test_consistency_between_anchored_sizes(client, case) -> None:
    await upload_evidence(client, case["case_id"], content=b"one")
    await client.post("/api/v1/anchors", json={}, headers=auth())
    for index in range(4):
        await upload_evidence(client, case["case_id"], content=f"more-{index}".encode())
    await client.post("/api/v1/anchors", json={}, headers=auth())

    result = (
        await client.get("/api/v1/anchoring/consistency?first=1&second=5", headers=auth())
    ).json()
    assert result["verified"] is True
    assert result["first"] == 1
    assert result["second"] == 5
    assert "no entry was removed" in result["detail"]


async def test_consistency_rejects_a_size_beyond_the_log(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    response = await client.get("/api/v1/anchoring/consistency?first=1&second=99", headers=auth())
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Proof bundles
# --------------------------------------------------------------------------
async def test_proof_bundle_is_cryptographically_self_contained(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    await client.post("/api/v1/anchors", json={}, headers=auth())

    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()

    # 1. manifest -> leaf
    recomputed_leaf = leaf_hash(canonical_json(bundle["manifest"])).hex()
    assert recomputed_leaf == bundle["leaf"]["leaf_hash"]

    # 2. leaf + path -> root
    assert verify_inclusion(
        bytes.fromhex(bundle["leaf"]["leaf_hash"]),
        bundle["leaf"]["index"],
        bundle["tree"]["tree_size"],
        [bytes.fromhex(node) for node in bundle["tree"]["inclusion_proof"]],
        bytes.fromhex(bundle["tree"]["root_hash"]),
    )

    # 3. root is the one that was signed
    assert bundle["tree"]["root_hash"] == bundle["signed_tree_head"]["root_hash"]

    # 4. signature verifies under the published key
    assert verify_signature(
        base64.b64decode(bundle["signature"]["public_key_b64"]),
        STH_DOMAIN + canonical_json(bundle["signed_tree_head"]),
        base64.b64decode(bundle["signature"]["value"]),
    )

    # 5. it is tied to a published anchor
    assert bundle["anchor"]["status"] == "CONFIRMED"
    assert bundle["anchor"]["backend"] == "local"


async def test_proof_bundle_contains_no_evidence_bytes(client, case) -> None:
    """Sharing a bundle must not share the evidence."""
    secret = b"CONFIDENTIAL-PAYLOAD-MARKER-9f3a"
    evidence = (await upload_evidence(client, case["case_id"], content=secret)).json()
    await client.post("/api/v1/anchors", json={}, headers=auth())
    raw = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).text
    assert b"CONFIDENTIAL-PAYLOAD-MARKER" not in raw.encode()
    assert evidence["sha256"] in raw


async def test_proof_bundle_states_when_nothing_is_anchored_yet(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()
    assert bundle["anchor"]["status"] == "NOT_ANCHORED"
    assert "self-attested" in bundle["anchor"]["detail"]


async def test_proof_bundle_documents_its_own_limits(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()
    disclaimers = " ".join(bundle["what_this_does_not_prove"]).lower()
    assert "authentic" in disclaimers
    assert "anchoring a forgery anchors a forgery" in disclaimers


async def test_proof_bundle_is_audited(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    trail = (
        await client.get("/api/v1/audit?action=PROOF_EXPORT", headers=auth(AUDITOR_TOKEN))
    ).json()
    assert trail["total"] == 1
    assert trail["items"][0]["evidence_id"] == evidence["evidence_id"]


async def test_proof_for_unknown_evidence_is_404(client) -> None:
    response = await client.get("/api/v1/evidence/EVD-nope/proof", headers=auth())
    assert response.status_code == 404


async def test_verify_bundle_endpoint_accepts_a_valid_bundle(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    await client.post("/api/v1/anchors", json={}, headers=auth())
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()

    result = (
        await client.post("/api/v1/anchoring/verify-bundle", json=bundle, headers=auth())
    ).json()
    assert result["verified"] is True
    assert result["checks"]["leaf_hash_matches_manifest"] is True
    assert result["checks"]["inclusion_proof_valid"] is True
    assert result["checks"]["signature_valid"] is True
    assert result["checks"]["externally_anchored"] is True
    assert result["caveats"]


async def test_verify_bundle_detects_a_doctored_manifest(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    await client.post("/api/v1/anchors", json={}, headers=auth())
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()

    bundle["manifest"]["body"]["sha256"] = "0" * 64
    result = (
        await client.post("/api/v1/anchoring/verify-bundle", json=bundle, headers=auth())
    ).json()
    assert result["verified"] is False
    assert result["checks"]["leaf_hash_matches_manifest"] is False
    assert any("does not hash to the leaf" in failure for failure in result["failures"])


async def test_verify_bundle_detects_a_swapped_root(client, case) -> None:
    evidence = (await upload_evidence(client, case["case_id"])).json()
    await client.post("/api/v1/anchors", json={}, headers=auth())
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()

    bundle["tree"]["root_hash"] = "1" * 64
    result = (
        await client.post("/api/v1/anchoring/verify-bundle", json=bundle, headers=auth())
    ).json()
    assert result["verified"] is False
    assert result["checks"]["inclusion_proof_valid"] is False
    assert result["checks"]["root_matches_signed_tree_head"] is False


async def test_verify_bundle_rejects_a_malformed_bundle(client) -> None:
    result = (
        await client.post("/api/v1/anchoring/verify-bundle", json={"nope": 1}, headers=auth())
    ).json()
    assert result["verified"] is False
    assert "malformed" in result["detail"].lower()


# --------------------------------------------------------------------------
# Backends and authorization
# --------------------------------------------------------------------------
async def test_backends_report_their_independence(client) -> None:
    items = (await client.get("/api/v1/anchoring/backends", headers=auth())).json()["items"]
    by_name = {item["name"]: item for item in items}
    assert by_name["local"]["independence"] == "SELF_ATTESTED"
    assert by_name["local"]["available"] is True
    assert by_name["local"]["is_default"] is True
    assert by_name["opentimestamps"]["independence"] == "PUBLIC_BLOCKCHAIN"
    assert by_name["file"]["independence"] == "SELF_ATTESTED"


async def test_investigator_can_read_but_not_create_anchors(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    assert (
        await client.get("/api/v1/anchoring/log", headers=auth(INVESTIGATOR_TOKEN))
    ).status_code == 200
    denied = await client.post("/api/v1/anchors", json={}, headers=auth(INVESTIGATOR_TOKEN))
    assert denied.status_code == 403
    assert "anchor:create" in denied.json()["detail"]


async def test_analyst_and_auditor_can_read_the_log(client) -> None:
    for token in (ANALYST_TOKEN, AUDITOR_TOKEN):
        assert (await client.get("/api/v1/anchoring/log", headers=auth(token))).status_code == 200


async def test_viewer_cannot_read_the_log(client) -> None:
    assert (
        await client.get("/api/v1/anchoring/log", headers=auth(VIEWER_TOKEN))
    ).status_code == 403


async def test_anchor_is_not_visible_across_tenants(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()
    response = await client.get(
        f"/api/v1/anchors/{anchor['anchor_id']}", headers=auth(OTHER_TENANT_TOKEN)
    )
    assert response.status_code == 404


async def test_receipt_download_returns_the_backend_payload(client, case) -> None:
    await upload_evidence(client, case["case_id"])
    anchor = (await client.post("/api/v1/anchors", json={}, headers=auth())).json()
    response = await client.get(
        f"/api/v1/anchors/{anchor['anchor_id']}/receipt", headers=auth()
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert anchor["root_hash"] in response.text


async def test_there_is_no_api_to_mutate_the_log(client, app) -> None:
    """Append-only is enforced by the absence of any other verb."""
    schema = app.openapi()
    log_paths = {
        path: ops for path, ops in schema["paths"].items() if path.startswith("/api/v1/anchoring/log")
    }
    assert log_paths
    for path, operations in log_paths.items():
        assert set(operations) <= {"get"}, f"{path} exposes a mutating method"
