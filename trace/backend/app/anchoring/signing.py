"""Signing of tree heads.

A Merkle root on its own says "these entries hash to this value". A *signed*
root additionally says "TRACE asserts this was the state of the log at this
time" — which is what makes the later anchor attributable rather than just an
anonymous 32 bytes on a ledger.

Ed25519 is used deliberately: no curve or parameter choices to get wrong, no
nonce-reuse failure mode, small keys and signatures, and it is available in
every serious KMS/HSM.

**Signature domain separation.** Every signed payload is prefixed with
``TRACE-STH-v1\\x00``. Without it, a signature produced over one kind of
structure could be replayed as another.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.anchoring.manifest import canonical_json
from app.core.timeutil import isoformat, utcnow

logger = logging.getLogger(__name__)

SIGNATURE_ALGORITHM = "ed25519"
STH_VERSION = "1"
#: Domain separation prefix — see the module docstring.
STH_DOMAIN = b"TRACE-STH-v1\x00"


def key_fingerprint(public_key_raw: bytes) -> str:
    """Stable short identifier for a public key."""
    return hashlib.sha256(public_key_raw).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class SignedTreeHead:
    """A signed assertion about the state of a log at a point in time."""

    log_id: str
    tree_size: int
    root_hash: str
    timestamp: str
    key_id: str
    signature: str
    algorithm: str = SIGNATURE_ALGORITHM
    sth_version: str = STH_VERSION
    previous_tree_size: int | None = None
    previous_root_hash: str | None = None

    def signed_payload(self) -> dict[str, Any]:
        """Exactly the fields covered by the signature."""
        return sth_payload(
            log_id=self.log_id,
            tree_size=self.tree_size,
            root_hash=self.root_hash,
            timestamp=self.timestamp,
            previous_tree_size=self.previous_tree_size,
            previous_root_hash=self.previous_root_hash,
        )

    def signing_bytes(self) -> bytes:
        return STH_DOMAIN + canonical_json(self.signed_payload())


def sth_payload(
    *,
    log_id: str,
    tree_size: int,
    root_hash: str,
    timestamp: str,
    previous_tree_size: int | None = None,
    previous_root_hash: str | None = None,
) -> dict[str, Any]:
    """The canonical, signature-covered representation of a tree head.

    ``key_id`` and ``signature`` are deliberately *not* covered — they describe
    the signature rather than the statement.
    """
    return {
        "sth_version": STH_VERSION,
        "log_id": log_id,
        "tree_size": tree_size,
        "root_hash": root_hash,
        "timestamp": timestamp,
        "previous_tree_size": previous_tree_size,
        "previous_root_hash": previous_root_hash,
    }


class Signer(ABC):
    """Produces signatures over tree heads.

    Implementations must never expose private key material through this
    interface — only the public key, the key id, and signatures.
    """

    algorithm: str = SIGNATURE_ALGORITHM

    @property
    @abstractmethod
    def key_id(self) -> str: ...

    @property
    @abstractmethod
    def public_key_raw(self) -> bytes: ...

    @abstractmethod
    def sign(self, payload: bytes) -> bytes: ...

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key_raw).decode("ascii")

    def public_key_pem(self) -> str:
        return (
            Ed25519PublicKey.from_public_bytes(self.public_key_raw)
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )

    def sign_tree_head(
        self,
        *,
        log_id: str,
        tree_size: int,
        root_hash: str,
        previous_tree_size: int | None = None,
        previous_root_hash: str | None = None,
        timestamp: str | None = None,
    ) -> SignedTreeHead:
        moment = timestamp or isoformat(utcnow())
        payload = sth_payload(
            log_id=log_id,
            tree_size=tree_size,
            root_hash=root_hash,
            timestamp=moment,
            previous_tree_size=previous_tree_size,
            previous_root_hash=previous_root_hash,
        )
        signature = self.sign(STH_DOMAIN + canonical_json(payload))
        return SignedTreeHead(
            log_id=log_id,
            tree_size=tree_size,
            root_hash=root_hash,
            timestamp=moment,
            key_id=self.key_id,
            signature=base64.b64encode(signature).decode("ascii"),
            algorithm=self.algorithm,
            previous_tree_size=previous_tree_size,
            previous_root_hash=previous_root_hash,
        )


class Ed25519Signer(Signer):
    """Ed25519 with the private key held in process memory.

    The key is loaded from a mounted PEM file or a base64 environment value —
    never from source. Suitable for self-hosted deployments; a deployment that
    needs the key never to touch application memory should implement
    :class:`Signer` against a KMS or HSM instead.
    """

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._key_id = key_fingerprint(self._public_raw)

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def public_key_raw(self) -> bytes:
        return self._public_raw

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)

    # ---- construction ------------------------------------------------------
    @classmethod
    def generate(cls) -> Ed25519Signer:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_pem_bytes(cls, pem: bytes, password: bytes | None = None) -> Ed25519Signer:
        key = serialization.load_pem_private_key(pem, password=password)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("TRACE log signing requires an Ed25519 private key")
        return cls(key)

    @classmethod
    def from_base64_seed(cls, seed_b64: str) -> Ed25519Signer:
        seed = base64.b64decode(seed_b64)
        if len(seed) != 32:
            raise ValueError("An Ed25519 private seed must be exactly 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    def private_key_pem(self) -> bytes:
        """Only used by the key-generation helper; never exposed through the API."""
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


class KmsSigner(Signer):
    """Signing delegated to a KMS/HSM so the private key never enters memory.

    Interface only — see docs/ROADMAP.md. It raises rather than silently
    falling back to an in-process key, because a deployment that asked for a
    KMS must not quietly get something weaker.
    """

    def __init__(self, key_reference: str) -> None:
        self.key_reference = key_reference

    @property
    def key_id(self) -> str:  # pragma: no cover - not implemented
        raise NotImplementedError(
            "KMS-backed signing is not implemented; set TRACE_ANCHOR_SIGNING_KEY_PATH instead."
        )

    @property
    def public_key_raw(self) -> bytes:  # pragma: no cover - not implemented
        raise NotImplementedError("KMS-backed signing is not implemented.")

    def sign(self, payload: bytes) -> bytes:  # pragma: no cover - not implemented
        raise NotImplementedError("KMS-backed signing is not implemented.")


def verify_signature(public_key_raw: bytes, payload: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature. Never raises on a bad signature."""
    try:
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(signature, payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def verify_tree_head(sth: SignedTreeHead, public_key_raw: bytes) -> bool:
    if sth.algorithm != SIGNATURE_ALGORITHM:
        return False
    if key_fingerprint(public_key_raw) != sth.key_id:
        return False
    try:
        signature = base64.b64decode(sth.signature)
    except (ValueError, TypeError):
        return False
    return verify_signature(public_key_raw, sth.signing_bytes(), signature)


def load_signer(
    *,
    key_path: str | None,
    key_seed_b64: str | None,
    allow_generate: bool,
    generated_key_path: str | None = None,
) -> Ed25519Signer:
    """Resolve the log signing key from configuration.

    Precedence: explicit seed -> mounted PEM file -> generated (development
    only, and only when the deployment opted in).
    """
    if key_seed_b64:
        logger.info("Log signing key loaded from TRACE_ANCHOR_SIGNING_KEY_SEED")
        return Ed25519Signer.from_base64_seed(key_seed_b64)

    if key_path:
        path = Path(key_path)
        if path.is_file():
            logger.info("Log signing key loaded from %s", path)
            return Ed25519Signer.from_pem_bytes(path.read_bytes())
        if not allow_generate:
            raise FileNotFoundError(
                f"Log signing key not found at {path}. Generate one with "
                f"`python scripts/generate_signing_key.py`, or set "
                f"TRACE_ANCHOR_ALLOW_KEY_GENERATION=true for local development."
            )

    if not allow_generate:
        raise ValueError(
            "No log signing key configured. Set TRACE_ANCHOR_SIGNING_KEY_PATH or "
            "TRACE_ANCHOR_SIGNING_KEY_SEED."
        )

    signer = Ed25519Signer.generate()
    logger.warning(
        "Generated an ephemeral log signing key (%s). Tree heads signed with it "
        "cannot be verified after a restart. Development use only.",
        signer.key_id,
    )
    if generated_key_path:
        target = Path(generated_key_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(signer.private_key_pem())
        os.chmod(target, 0o600)
        logger.warning("Persisted the generated signing key to %s (mode 600).", target)
    return signer
