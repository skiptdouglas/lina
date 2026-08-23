#!/usr/bin/env python3
"""Verify a TRACE proof bundle — offline, independently, with no TRACE code.

    python3 verify_anchor.py bundle.json [--evidence-file sysmon.jsonl]

A guarantee you can only check by asking the system under scrutiny is not a
guarantee. This script exists so that opposing counsel, an auditor, or a court
expert can verify a TRACE evidence bundle on a machine TRACE has never touched.

**Dependencies: none.** Python 3.9+ standard library only. Ed25519 verification
uses the `cryptography` package when it happens to be installed, and otherwise
falls back to the pure-Python RFC 8032 implementation included below, so this
file works on an air-gapped laptop with nothing but CPython.

What it checks
--------------
1. (with --evidence-file) the file's SHA-256 matches the manifest
2. the manifest hashes to the leaf recorded in the bundle
3. the audit path folds the leaf into the recorded root  (RFC 6962)
4. that root is the one inside the signed tree head
5. the Ed25519 signature over the tree head verifies
6. (with --expect-key-id) the signature was made by the key you expected
7. the anchor's status and independence, reported plainly

Exit code 0 means every applicable check passed.

**Pin the key.** A bundle carries the public key that signed it, so a forger
who re-signs a doctored bundle with their own key passes step 5. Obtain the
deployment's key id out of band — from the case report, the organisation's
published key, or a previous verified bundle — and pass it with
``--expect-key-id``. Without that, step 5 proves internal consistency, not
authorship.

What a pass does NOT mean
-------------------------
That the evidence is authentic, complete, or lawfully obtained. Anchoring a
forgery anchors a forgery. This proves an unbroken chain from a file you hold
to a signed, published commitment — nothing more, and nothing less.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# RFC 6962 Merkle verification
# ---------------------------------------------------------------------------
LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def verify_inclusion(leaf, index, tree_size, proof, root) -> bool:
    """RFC 6962 §2.1.1 audit-path verification."""
    if index < 0 or tree_size <= 0 or index >= tree_size:
        return False
    if len(leaf) != 32 or len(root) != 32 or any(len(n) != 32 for n in proof):
        return False
    fn, sn = index, tree_size - 1
    computed = leaf
    for sibling in proof:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            computed = node_hash(sibling, computed)
            while fn != 0 and not fn & 1:
                fn >>= 1
                sn >>= 1
        else:
            computed = node_hash(computed, sibling)
        fn >>= 1
        sn >>= 1
    return sn == 0 and computed == root


# ---------------------------------------------------------------------------
# Canonical JSON — must match app/anchoring/manifest.py byte for byte
# ---------------------------------------------------------------------------
def canonical_json(payload: Any) -> bytes:
    _reject_floats(payload)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise TypeError("Float at %s: manifests must not contain floating point values" % path)
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, "%s.%s" % (path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, "%s[%d]" % (path, index))


# ---------------------------------------------------------------------------
# Ed25519 verification (RFC 8032), pure Python fallback
#
# Verification only, over public data, so the non-constant-time arithmetic
# below is not a concern: there is no secret to leak.
# ---------------------------------------------------------------------------
_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493


def _modp_inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _modp_inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _modp_inv(_D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_G_Y = 4 * _modp_inv(5) % _P
_G_X = _recover_x(_G_Y, 0)
_G = (_G_X, _G_Y, 1, _G_X * _G_Y % _P)


def _point_add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _P
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _P
    C = 2 * P[3] * Q[3] * _D % _P
    D = 2 * P[2] * Q[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _point_mul(s: int, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        s >>= 1
    return Q


def _point_equal(P, Q) -> bool:
    if (P[0] * Q[2] - Q[0] * P[2]) % _P != 0:
        return False
    return (P[1] * Q[2] - Q[1] * P[2]) % _P == 0


def _point_decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _sha512_modq(s: bytes) -> int:
    return int.from_bytes(hashlib.sha512(s).digest(), "little") % _Q


def ed25519_verify_pure(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7 verification, transcribed from the reference code."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    A = _point_decompress(public_key)
    if A is None:
        return False
    r_bytes = signature[:32]
    R = _point_decompress(r_bytes)
    if R is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_modq(r_bytes + public_key + message)
    return _point_equal(_point_mul(s, _G), _point_add(R, _point_mul(h, A)))


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes):
    """Prefer the audited library when present; fall back to pure Python."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
            return True, "cryptography"
        except (InvalidSignature, ValueError):
            return False, "cryptography"
    except BaseException as exc:  # noqa: BLE001
        # Not just ImportError: a broken or partially-installed `cryptography`
        # can raise at import time from its Rust bindings with an exception
        # that does not derive from Exception. A standalone forensic tool must
        # degrade to the pure-Python path rather than crash.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return ed25519_verify_pure(public_key, message, signature), "pure-python"


# ---------------------------------------------------------------------------
# Bundle verification
# ---------------------------------------------------------------------------
STH_DOMAIN = b"TRACE-STH-v1\x00"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


class Report:
    def __init__(self, colour: bool = True) -> None:
        self.checks = []
        self.colour = colour

    def add(self, name: str, ok, detail: str = "") -> None:
        self.checks.append({"check": name, "result": ok, "detail": detail})

    def _paint(self, text: str, code: str) -> str:
        return "%s%s%s" % (code, text, RESET) if self.colour else text

    def render(self) -> str:
        lines = []
        for entry in self.checks:
            if entry["result"] is None:
                mark = self._paint("SKIP", YELLOW)
            elif entry["result"]:
                mark = self._paint("PASS", GREEN)
            else:
                mark = self._paint("FAIL", RED)
            lines.append("  [%s] %s" % (mark, entry["check"]))
            if entry["detail"]:
                lines.append("         %s" % self._paint(entry["detail"], DIM))
        return "\n".join(lines)

    @property
    def passed(self) -> bool:
        return all(entry["result"] is not False for entry in self.checks)


def verify_bundle(
    bundle: dict, evidence_path=None, colour: bool = True, expect_key_id=None
) -> Report:
    report = Report(colour=colour)

    manifest = bundle.get("manifest") or {}
    leaf = bundle.get("leaf") or {}
    tree = bundle.get("tree") or {}
    sth = bundle.get("signed_tree_head") or {}
    signature_block = bundle.get("signature") or {}
    anchor = bundle.get("anchor") or {}
    body = manifest.get("body") or {}

    # 1. evidence file -> manifest digest
    if evidence_path:
        digest = hashlib.sha256()
        size = 0
        with open(evidence_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        actual = digest.hexdigest()
        expected = body.get("sha256")
        report.add(
            "Evidence file matches the manifest digest",
            actual == expected,
            "expected %s\n         actual   %s" % (expected, actual),
        )
        if body.get("size") is not None:
            report.add(
                "Evidence file size matches the manifest",
                size == body.get("size"),
                "manifest %s bytes, file %s bytes" % (body.get("size"), size),
            )
    else:
        report.add(
            "Evidence file matches the manifest digest",
            None,
            "no --evidence-file given; the manifest digest was not checked against a file",
        )

    # 2. manifest -> leaf hash
    try:
        recomputed = leaf_hash(canonical_json(manifest)).hex()
        report.add(
            "Manifest hashes to the recorded leaf",
            recomputed == leaf.get("leaf_hash"),
            "leaf %s" % leaf.get("leaf_hash"),
        )
    except (TypeError, ValueError) as exc:
        report.add("Manifest hashes to the recorded leaf", False, str(exc))

    # 3. leaf + audit path -> root
    try:
        ok = verify_inclusion(
            binascii.unhexlify(leaf["leaf_hash"]),
            int(leaf["index"]),
            int(tree["tree_size"]),
            [binascii.unhexlify(node) for node in tree["inclusion_proof"]],
            binascii.unhexlify(tree["root_hash"]),
        )
        report.add(
            "Audit path folds the leaf into the root",
            ok,
            "entry %s of %s, %s proof node(s)"
            % (leaf.get("index"), tree.get("tree_size"), len(tree.get("inclusion_proof", []))),
        )
    except (KeyError, ValueError, TypeError, binascii.Error) as exc:
        report.add("Audit path folds the leaf into the root", False, "malformed proof: %s" % exc)

    # 4. root == signed root
    report.add(
        "Signed tree head commits to that root",
        tree.get("root_hash") == sth.get("root_hash") and bool(sth.get("root_hash")),
        "root %s" % tree.get("root_hash"),
    )

    # 5. signature
    try:
        public_key = base64.b64decode(signature_block["public_key_b64"])
        raw_signature = base64.b64decode(signature_block["value"])
        payload = STH_DOMAIN + canonical_json(sth)
        ok, implementation = ed25519_verify(public_key, payload, raw_signature)
        report.add(
            "Tree-head signature verifies",
            ok,
            "ed25519 key %s (via %s)" % (signature_block.get("key_id"), implementation),
        )
    except (KeyError, ValueError, TypeError, binascii.Error) as exc:
        report.add("Tree-head signature verifies", False, "malformed signature block: %s" % exc)

    # 6. key pinning — the difference between "consistent" and "authentic"
    actual_key_id = signature_block.get("key_id")
    if expect_key_id:
        report.add(
            "Signing key is the one you expected",
            actual_key_id == expect_key_id,
            "expected %s\n         actual   %s" % (expect_key_id, actual_key_id),
        )
    else:
        report.add(
            "Signing key is the one you expected",
            None,
            "no --expect-key-id given. This bundle was signed by key %s;\n"
            "         compare it with the deployment's published key, or a\n"
            "         forged bundle signed with an attacker's key would also pass."
            % actual_key_id,
        )

    # 6. anchor
    status = anchor.get("status")
    independence = anchor.get("independence", "UNKNOWN")
    if status in ("CONFIRMED", "SUBMITTED"):
        note = "%s on '%s' (%s)" % (status, anchor.get("backend"), independence)
        if anchor.get("external_ref"):
            note += "\n         ref %s" % anchor["external_ref"]
        if independence == "SELF_ATTESTED":
            note += (
                "\n         self-attested by TRACE — not independent third-party evidence"
            )
        report.add("Root is published to a ledger", status == "CONFIRMED", note)
    else:
        report.add(
            "Root is published to a ledger",
            False,
            "not anchored: the tree head is signed but not published anywhere",
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a TRACE evidence proof bundle, offline.",
        epilog="Exit code 0 means every applicable check passed.",
    )
    parser.add_argument("bundle", help="Path to the proof bundle JSON")
    parser.add_argument(
        "--evidence-file",
        help="The evidence file itself, to confirm it hashes to the manifest digest",
    )
    parser.add_argument(
        "--expect-key-id",
        help="Pin the signing key id obtained out of band (strongly recommended)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--no-colour", action="store_true", help="Disable ANSI colour")
    args = parser.parse_args()

    try:
        with open(args.bundle, "r", encoding="utf-8") as handle:
            bundle = json.load(handle)
    except (OSError, ValueError) as exc:
        print("Could not read the bundle: %s" % exc, file=sys.stderr)
        return 2

    colour = not args.no_colour and sys.stdout.isatty()
    report = verify_bundle(
        bundle, args.evidence_file, colour=colour, expect_key_id=args.expect_key_id
    )

    if args.json:
        print(
            json.dumps(
                {
                    "verified": report.passed,
                    "evidence_id": bundle.get("evidence_id"),
                    "checks": report.checks,
                    "what_this_does_not_prove": bundle.get("what_this_does_not_prove", []),
                },
                indent=2,
            )
        )
        return 0 if report.passed else 1

    print("TRACE proof bundle verification")
    print("=" * 60)
    print("Evidence : %s" % bundle.get("evidence_id"))
    print("Case     : %s" % (bundle.get("manifest", {}).get("body", {}).get("case_id")))
    print("Log entry: %s of %s" % (
        bundle.get("leaf", {}).get("index"), bundle.get("tree", {}).get("tree_size")
    ))
    print()
    print(report.render())
    print()
    if report.passed:
        banner = "VERIFIED — the chain from this file to a signed, published root is intact."
        print(banner if not colour else GREEN + banner + RESET)
    else:
        banner = "FAILED — see the checks above. Do not rely on this bundle."
        print(banner if not colour else RED + banner + RESET)

    print()
    print("This does NOT prove:")
    for caveat in bundle.get(
        "what_this_does_not_prove",
        ["That the evidence is authentic or lawfully obtained."],
    ):
        print("  - %s" % caveat)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
