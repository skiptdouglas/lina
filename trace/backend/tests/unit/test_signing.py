"""Ed25519 tree-head signing."""

from __future__ import annotations

import base64

import pytest

from app.anchoring.manifest import canonical_json
from app.anchoring.signing import (
    STH_DOMAIN,
    Ed25519Signer,
    KmsSigner,
    key_fingerprint,
    load_signer,
    verify_signature,
    verify_tree_head,
)


def test_sign_and_verify_a_tree_head() -> None:
    signer = Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t:evidence", tree_size=7, root_hash="ab" * 32)
    assert verify_tree_head(sth, signer.public_key_raw)


def test_signature_does_not_verify_under_another_key() -> None:
    signer, impostor = Ed25519Signer.generate(), Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t:evidence", tree_size=7, root_hash="ab" * 32)
    assert not verify_tree_head(sth, impostor.public_key_raw)


@pytest.mark.parametrize("field", ["tree_size", "root_hash", "log_id", "timestamp"])
def test_tampering_with_any_signed_field_breaks_the_signature(field: str) -> None:
    signer = Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t:evidence", tree_size=7, root_hash="ab" * 32)
    payload = sth.signed_payload()
    payload[field] = 99 if field == "tree_size" else "tampered"
    assert not verify_signature(
        signer.public_key_raw,
        STH_DOMAIN + canonical_json(payload),
        base64.b64decode(sth.signature),
    )


def test_signature_is_domain_separated() -> None:
    """A signature over the bare payload must not verify as a tree head."""
    signer = Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t:evidence", tree_size=1, root_hash="cd" * 32)
    undomained = canonical_json(sth.signed_payload())
    assert not verify_signature(
        signer.public_key_raw, undomained, base64.b64decode(sth.signature)
    )
    assert verify_signature(
        signer.public_key_raw, STH_DOMAIN + undomained, base64.b64decode(sth.signature)
    )


def test_key_id_and_signature_are_absent_from_the_signed_payload() -> None:
    """They describe the signature, not the statement it makes."""
    signer = Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t:evidence", tree_size=1, root_hash="cd" * 32)
    assert "key_id" not in sth.signed_payload()
    assert "signature" not in sth.signed_payload()


def test_key_id_is_a_stable_fingerprint_of_the_public_key() -> None:
    signer = Ed25519Signer.generate()
    assert signer.key_id == key_fingerprint(signer.public_key_raw)
    assert len(signer.key_id) == 32
    restored = Ed25519Signer.from_pem_bytes(signer.private_key_pem())
    assert restored.key_id == signer.key_id


def test_verify_rejects_a_mismatched_key_id() -> None:
    signer, other = Ed25519Signer.generate(), Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t", tree_size=1, root_hash="ef" * 32)
    object.__setattr__(sth, "key_id", other.key_id)
    assert not verify_tree_head(sth, signer.public_key_raw)


def test_verify_rejects_a_malformed_signature_without_raising() -> None:
    signer = Ed25519Signer.generate()
    sth = signer.sign_tree_head(log_id="t", tree_size=1, root_hash="ef" * 32)
    object.__setattr__(sth, "signature", "not base64 !!")
    assert not verify_tree_head(sth, signer.public_key_raw)


def test_seed_round_trip_is_deterministic() -> None:
    seed = base64.b64encode(bytes(range(32))).decode()
    assert Ed25519Signer.from_base64_seed(seed).key_id == (
        Ed25519Signer.from_base64_seed(seed).key_id
    )


def test_seed_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        Ed25519Signer.from_base64_seed(base64.b64encode(b"short").decode())


def test_public_key_pem_is_exportable() -> None:
    pem = Ed25519Signer.generate().public_key_pem()
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")


def test_kms_signer_refuses_rather_than_falling_back() -> None:
    """A deployment that asked for a KMS must not silently get something weaker."""
    signer = KmsSigner("arn:aws:kms:eu-west-1:...:key/abc")
    with pytest.raises(NotImplementedError):
        _ = signer.key_id
    with pytest.raises(NotImplementedError):
        signer.sign(b"payload")


def test_load_signer_refuses_to_generate_unless_allowed(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Log signing key not found"):
        load_signer(
            key_path=str(tmp_path / "absent.pem"),
            key_seed_b64=None,
            allow_generate=False,
        )


def test_load_signer_persists_a_generated_key(tmp_path) -> None:
    target = tmp_path / "keys" / "log.pem"
    signer = load_signer(
        key_path=str(target),
        key_seed_b64=None,
        allow_generate=True,
        generated_key_path=str(target),
    )
    assert target.is_file()
    assert (target.stat().st_mode & 0o777) == 0o600
    assert load_signer(
        key_path=str(target), key_seed_b64=None, allow_generate=False
    ).key_id == signer.key_id


def test_load_signer_prefers_the_seed_over_a_file(tmp_path) -> None:
    seed = base64.b64encode(bytes(range(32))).decode()
    signer = load_signer(
        key_path=str(tmp_path / "unused.pem"), key_seed_b64=seed, allow_generate=False
    )
    assert signer.key_id == Ed25519Signer.from_base64_seed(seed).key_id
