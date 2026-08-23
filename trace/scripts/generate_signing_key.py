#!/usr/bin/env python3
"""Generate the Ed25519 key TRACE uses to sign Merkle tree heads.

    python3 scripts/generate_signing_key.py --out deploy/keys/log-signing-key.pem

The key is what makes an anchored root attributable to this deployment rather
than anonymous bytes on a ledger. Two consequences worth understanding before
you run this:

* **Losing it does not invalidate past anchors.** Published roots stay
  verifiable against the *public* key, which is embedded in every proof
  bundle. You simply cannot sign new tree heads until you generate a
  replacement.
* **Leaking it lets someone sign tree heads in your name.** Treat it like a
  code-signing key: mount it read-only, keep it out of travelling backups, and
  prefer a KMS/HSM in production.

**Dependencies: none.** Uses `cryptography` when installed and otherwise falls
back to the pure-Python RFC 8032 derivation below, so `make init` works on a
bare machine. Key material comes from `secrets.token_bytes` either way.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import pathlib
import secrets
import textwrap

# ---------------------------------------------------------------------------
# Pure-Python Ed25519 public-key derivation (RFC 8032 §5.1.5)
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


def _point_compress(P) -> bytes:
    zinv = _modp_inv(P[2])
    x = P[0] * zinv % _P
    y = P[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def public_key_from_seed_pure(seed: bytes) -> bytes:
    """RFC 8032 §5.1.5: clamp SHA-512(seed)[:32], multiply the base point."""
    h = bytearray(hashlib.sha512(seed).digest()[:32])
    h[0] &= 248
    h[31] &= 127
    h[31] |= 64
    return _point_compress(_point_mul(int.from_bytes(h, "little"), _G))


def public_key_from_seed(seed: bytes):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.from_private_bytes(seed)
        raw = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return raw, "cryptography"
    except BaseException as exc:  # noqa: BLE001
        # Not just ImportError: a broken or partially-installed `cryptography`
        # can raise at import time from its Rust bindings with an exception
        # that does not derive from Exception. A standalone forensic tool must
        # degrade to the pure-Python path rather than crash.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return public_key_from_seed_pure(seed), "pure-python"


# ---------------------------------------------------------------------------
# DER / PEM encoding
#
# Ed25519 keys have fixed-length ASN.1 structures (RFC 8410), so these are
# constant prefixes rather than a general DER encoder. `test_signing_key_script`
# round-trips the output through the `cryptography` loader.
# ---------------------------------------------------------------------------
PKCS8_ED25519_PREFIX = bytes.fromhex("302e020100300506032b657004220420")
SPKI_ED25519_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _pem(der: bytes, label: str) -> bytes:
    body = "\n".join(textwrap.wrap(base64.b64encode(der).decode("ascii"), 64))
    return ("-----BEGIN %s-----\n%s\n-----END %s-----\n" % (label, body, label)).encode("ascii")


def private_key_pem(seed: bytes) -> bytes:
    return _pem(PKCS8_ED25519_PREFIX + seed, "PRIVATE KEY")


def public_key_pem(public_raw: bytes) -> bytes:
    return _pem(SPKI_ED25519_PREFIX + public_raw, "PUBLIC KEY")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="deploy/keys/log-signing-key.pem",
        help="Where to write the PEM private key",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing key")
    parser.add_argument(
        "--print-seed",
        action="store_true",
        help="Also print a base64 seed for TRACE_ANCHOR_SIGNING_KEY_SEED",
    )
    args = parser.parse_args()

    target = pathlib.Path(args.out)
    if target.exists() and not args.force:
        print(
            "%s already exists. Refusing to overwrite it — a new key cannot sign\n"
            "for the old one. Use --force only if you mean it." % target
        )
        return 0

    seed = secrets.token_bytes(32)
    public_raw, implementation = public_key_from_seed(seed)
    key_id = hashlib.sha256(public_raw).hexdigest()[:32]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(private_key_pem(seed))
    os.chmod(target, 0o600)

    public_path = target.with_suffix(".pub.pem")
    public_path.write_bytes(public_key_pem(public_raw))

    print("Wrote %s (mode 600)" % target)
    print("Wrote %s" % public_path)
    print()
    print("  key id      : %s" % key_id)
    print("  public key  : %s" % base64.b64encode(public_raw).decode())
    print("  derived via : %s" % implementation)
    print()
    print("Point TRACE at it:")
    print("  TRACE_ANCHOR_SIGNING_KEY_PATH=%s" % target)
    if args.print_seed:
        print()
        print("Or, as an environment secret:")
        print("  TRACE_ANCHOR_SIGNING_KEY_SEED=%s" % base64.b64encode(seed).decode())
    print()
    print("Publish the public key and key id alongside your case reports: they are")
    print("what let anyone verify a TRACE proof bundle without trusting TRACE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
