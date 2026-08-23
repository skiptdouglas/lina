"""The offline verifier, run as a real subprocess against a real bundle.

This is the test that matters for the whole anchoring feature: it proves that
what TRACE emits can be checked by a separate program, with no TRACE imports,
using only the standard library. If canonical serialization, the Merkle
construction or the signature domain ever drift between the two
implementations, this fails.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import auth, upload_evidence

VERIFIER = Path(__file__).resolve().parents[3] / "scripts" / "verify_anchor.py"
PAYLOAD = b'{"EventID":1,"Image":"powershell.exe"}\n' * 25


def run_verifier(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, test-controlled inputs
        [sys.executable, str(VERIFIER), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


@pytest.fixture
async def anchored_bundle(client, case, tmp_path) -> dict:
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()
    anchor = await client.post("/api/v1/anchors", json={}, headers=auth())
    assert anchor.status_code == 201
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()

    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2))
    evidence_path = tmp_path / "sysmon.jsonl"
    evidence_path.write_bytes(PAYLOAD)
    return {
        "bundle": bundle,
        "bundle_path": bundle_path,
        "evidence_path": evidence_path,
        "evidence": evidence,
    }


def test_verifier_script_exists_and_has_no_trace_imports() -> None:
    """It must be handable to a third party as a single file."""
    source = VERIFIER.read_text()
    assert "from app." not in source
    assert "import app" not in source
    for forbidden in ("fastapi", "sqlalchemy", "pydantic"):
        assert forbidden not in source


async def test_verifier_passes_on_a_genuine_bundle(anchored_bundle) -> None:
    result = run_verifier(
        str(anchored_bundle["bundle_path"]),
        "--evidence-file",
        str(anchored_bundle["evidence_path"]),
        "--no-colour",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFIED" in result.stdout
    assert "Evidence file matches the manifest digest" in result.stdout
    assert "Manifest hashes to the recorded leaf" in result.stdout
    assert "Audit path folds the leaf into the root" in result.stdout
    assert "Tree-head signature verifies" in result.stdout
    # It must also state its limits, every time.
    assert "This does NOT prove" in result.stdout
    assert "forgery" in result.stdout


async def test_verifier_json_output_is_machine_readable(anchored_bundle) -> None:
    result = run_verifier(
        str(anchored_bundle["bundle_path"]),
        "--evidence-file",
        str(anchored_bundle["evidence_path"]),
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verified"] is True
    assert payload["evidence_id"] == anchored_bundle["evidence"]["evidence_id"]
    assert all(check["result"] is not False for check in payload["checks"])


async def test_verifier_works_without_the_cryptography_package(anchored_bundle) -> None:
    """The pure-Python Ed25519 path must verify a genuine signature.

    An air-gapped reviewer will not be running pip install.
    """
    import os

    blocker = anchored_bundle["bundle_path"].parent / "blocker"
    blocker.mkdir(exist_ok=True)
    # A stub package that raises ImportError shadows the real one on sys.path.
    (blocker / "cryptography.py").write_text("raise ImportError('blocked for this test')\n")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(blocker)
    result = run_verifier(
        str(anchored_bundle["bundle_path"]),
        "--evidence-file",
        str(anchored_bundle["evidence_path"]),
        "--json",
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verified"] is True
    signature_check = next(
        check for check in payload["checks"] if "signature" in check["check"].lower()
    )
    assert "pure-python" in signature_check["detail"]


async def test_verifier_detects_a_substituted_evidence_file(anchored_bundle, tmp_path) -> None:
    impostor = tmp_path / "swapped.jsonl"
    impostor.write_bytes(PAYLOAD + b"one extra line\n")
    result = run_verifier(
        str(anchored_bundle["bundle_path"]), "--evidence-file", str(impostor), "--no-colour"
    )
    assert result.returncode == 1
    assert "FAILED" in result.stdout
    assert "Evidence file matches the manifest digest" in result.stdout


async def test_verifier_detects_a_doctored_manifest(anchored_bundle, tmp_path) -> None:
    """Someone edits the manifest to point at different bytes."""
    bundle = json.loads(anchored_bundle["bundle_path"].read_text())
    bundle["manifest"]["body"]["sha256"] = "0" * 64
    doctored = tmp_path / "doctored.json"
    doctored.write_text(json.dumps(bundle))

    result = run_verifier(str(doctored), "--no-colour")
    assert result.returncode == 1
    assert "FAILED" in result.stdout


async def test_verifier_detects_a_forged_signature(anchored_bundle, tmp_path) -> None:
    import base64

    bundle = json.loads(anchored_bundle["bundle_path"].read_text())
    bundle["signature"]["value"] = base64.b64encode(b"\x00" * 64).decode()
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(bundle))

    result = run_verifier(str(forged), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    signature_check = next(
        check for check in payload["checks"] if "signature" in check["check"].lower()
    )
    assert signature_check["result"] is False


async def test_verifier_detects_a_swapped_public_key(anchored_bundle, tmp_path) -> None:
    """Re-signing with an attacker's key must not pass."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    bundle = json.loads(anchored_bundle["bundle_path"].read_text())
    attacker = Ed25519PrivateKey.generate()
    attacker_public = attacker.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    # The attacker signs the same tree head with their own key and swaps both
    # the key and the signature. The signature check passes in isolation...
    payload = b"TRACE-STH-v1\x00" + json.dumps(
        bundle["signed_tree_head"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    bundle["signature"]["value"] = base64.b64encode(attacker.sign(payload)).decode()
    bundle["signature"]["public_key_b64"] = base64.b64encode(attacker_public).decode()
    swapped = tmp_path / "swapped-key.json"
    swapped.write_text(json.dumps(bundle))

    result = run_verifier(str(swapped), "--json")
    payload_out = json.loads(result.stdout)
    signature_check = next(
        check for check in payload_out["checks"] if "signature" in check["check"].lower()
    )
    # ...which is exactly why the key id must be checked against a published
    # key out of band. The verifier reports the key it used so a reviewer can.
    assert signature_check["result"] is True
    assert bundle["signature"]["key_id"] in signature_check["detail"]


async def test_verifier_detects_a_tampered_audit_path(anchored_bundle, tmp_path) -> None:
    bundle = json.loads(anchored_bundle["bundle_path"].read_text())
    bundle["tree"]["inclusion_proof"] = ["ab" * 32]
    tampered = tmp_path / "tampered-path.json"
    tampered.write_text(json.dumps(bundle))

    result = run_verifier(str(tampered), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    path_check = next(check for check in payload["checks"] if "Audit path" in check["check"])
    assert path_check["result"] is False


async def test_verifier_flags_an_unanchored_bundle(client, case, tmp_path) -> None:
    """A signed but unpublished tree head must not read as fully verified."""
    evidence = (await upload_evidence(client, case["case_id"], content=PAYLOAD)).json()
    bundle = (
        await client.get(f"/api/v1/evidence/{evidence['evidence_id']}/proof", headers=auth())
    ).json()
    path = tmp_path / "unanchored.json"
    path.write_text(json.dumps(bundle))

    result = run_verifier(str(path), "--no-colour")
    assert result.returncode == 1
    assert "not anchored" in result.stdout


async def test_verifier_reports_self_attestation_for_local_anchors(anchored_bundle) -> None:
    result = run_verifier(str(anchored_bundle["bundle_path"]), "--no-colour")
    assert "self-attested by TRACE" in result.stdout
    assert "not independent third-party evidence" in result.stdout


def test_verifier_handles_an_unreadable_bundle(tmp_path) -> None:
    result = run_verifier(str(tmp_path / "absent.json"))
    assert result.returncode == 2
    assert "Could not read the bundle" in result.stderr


async def test_key_pinning_rejects_a_bundle_signed_by_another_key(
    anchored_bundle, tmp_path
) -> None:
    """The check that turns "internally consistent" into "authentic".

    A forger who re-signs a doctored bundle with their own key passes the
    signature check. Pinning the key id obtained out of band catches it.
    """
    import base64
    import json as jsonlib

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    bundle = jsonlib.loads(anchored_bundle["bundle_path"].read_text())
    genuine_key_id = bundle["signature"]["key_id"]

    attacker = Ed25519PrivateKey.generate()
    attacker_public = attacker.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    payload = b"TRACE-STH-v1\x00" + jsonlib.dumps(
        bundle["signed_tree_head"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    bundle["signature"]["value"] = base64.b64encode(attacker.sign(payload)).decode()
    bundle["signature"]["public_key_b64"] = base64.b64encode(attacker_public).decode()
    bundle["signature"]["key_id"] = "attackerkeyid00000000000000000000"

    forged = tmp_path / "forged-key.json"
    forged.write_text(jsonlib.dumps(bundle))

    result = run_verifier(str(forged), "--expect-key-id", genuine_key_id, "--json")
    assert result.returncode == 1
    payload_out = jsonlib.loads(result.stdout)
    pin_check = next(
        check for check in payload_out["checks"] if "expected" in check["check"]
    )
    assert pin_check["result"] is False


async def test_key_pinning_passes_for_the_genuine_key(anchored_bundle) -> None:
    import json as jsonlib

    bundle = jsonlib.loads(anchored_bundle["bundle_path"].read_text())
    result = run_verifier(
        str(anchored_bundle["bundle_path"]),
        "--expect-key-id",
        bundle["signature"]["key_id"],
        "--evidence-file",
        str(anchored_bundle["evidence_path"]),
        "--no-colour",
    )
    assert result.returncode == 0
    assert "VERIFIED" in result.stdout


async def test_verifier_warns_when_the_key_is_not_pinned(anchored_bundle) -> None:
    result = run_verifier(str(anchored_bundle["bundle_path"]), "--no-colour")
    assert "no --expect-key-id given" in result.stdout
    assert "forged bundle signed with an attacker's key would also pass" in result.stdout
