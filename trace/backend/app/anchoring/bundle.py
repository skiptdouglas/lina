"""Proof bundles — the artefact a third party actually verifies.

A bundle is everything needed to check one evidence object's place in the log
**without TRACE**: the manifest, its position, the audit path, the signed tree
head, the public key and the anchor receipt. Hand it to opposing counsel with
``scripts/verify_anchor.py`` and they can confirm it on an air-gapped laptop.

That is the point of the whole feature. A guarantee that can only be checked by
asking the system under scrutiny is not a guarantee.

The bundle deliberately contains **no evidence bytes** — only the manifest of
immutable facts and hashes. Sharing a bundle does not share the evidence.
"""

from __future__ import annotations

from typing import Any

BUNDLE_VERSION = "1"

VERIFICATION_STEPS = (
    "Recompute SHA-256 over the evidence file and compare it with manifest.body.sha256.",
    "Re-serialize the manifest canonically and hash it: SHA-256(0x00 || bytes) = leaf_hash.",
    "Fold leaf_hash with inclusion_proof to recompute root_hash (RFC 6962).",
    "Check root_hash matches the root in the signed tree head.",
    "Verify the Ed25519 signature over the tree head with the published public key.",
    "Check the anchor receipt commits to the same root, on whatever ledger it names.",
)


def build_bundle(
    *,
    evidence_id: str,
    manifest: dict[str, Any],
    leaf_index: int,
    leaf_hash: str,
    entry_hash: str,
    tree_size: int,
    root_hash: str,
    inclusion_proof: list[str],
    signed_tree_head: dict[str, Any],
    signature: str,
    key_id: str,
    public_key_b64: str,
    algorithm: str,
    anchor: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble a self-contained, offline-verifiable proof bundle."""
    return {
        "bundle_version": BUNDLE_VERSION,
        "produced_by": "TRACE",
        "evidence_id": evidence_id,
        "manifest": manifest,
        "entry_hash": entry_hash,
        "leaf": {
            "index": leaf_index,
            "leaf_hash": leaf_hash,
            "hash_construction": (
                "RFC6962: leaf = SHA-256(0x00 || canonical_manifest_bytes)"
            ),
        },
        "tree": {
            "tree_size": tree_size,
            "root_hash": root_hash,
            "inclusion_proof": inclusion_proof,
        },
        "signed_tree_head": signed_tree_head,
        "signature": {
            "algorithm": algorithm,
            "key_id": key_id,
            "public_key_b64": public_key_b64,
            "value": signature,
            "domain_prefix_hex": b"TRACE-STH-v1\x00".hex(),
        },
        "anchor": anchor,
        "how_to_verify": {
            "offline_tool": "scripts/verify_anchor.py",
            "usage": "python scripts/verify_anchor.py bundle.json [--evidence-file FILE]",
            "steps": list(VERIFICATION_STEPS),
        },
        "what_this_proves": [
            "The evidence file hashes to the digest recorded in the manifest.",
            "That manifest is entry N of a log whose root was signed by the named key.",
            "The log has not been reordered or rewritten below that root.",
            "The root was published to the anchor named below at the time it records.",
        ],
        "what_this_does_not_prove": [
            "That the evidence is authentic, complete, or lawfully obtained — "
            "anchoring a forgery anchors a forgery.",
            "Who created the underlying artifact; the signature attests to key custody only.",
            "Anything about entries added after this tree size.",
        ],
    }
