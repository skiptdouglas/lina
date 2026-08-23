"""Log entries: what actually gets hashed into a Merkle leaf.

An entry must be **canonically serializable**: the same evidence object must
produce byte-identical output today and in five years, on any machine, or the
anchor it sits under stops verifying.

## Only immutable facts are committed

This is the decision that makes or breaks the design. An evidence row carries
both immutable facts (its digest, its size, when it was collected) and mutable
state (legal hold, parse status, when it was last verified). Committing a
mutable field would mean that flipping a legal hold silently invalidates every
proof issued before the flip.

So the manifest contains *only* what can never legitimately change:

============================  ===========================================
Committed                     Excluded (mutable by design)
============================  ===========================================
evidence_id                   legal_hold
tenant_id / case_id           retention_policy
sha256 / size                 parse_status / parse_detail
original_filename / path      last_verified_at / last_verification_result
source / source_type          notes
collector                     
acquisition_method
collection_timestamp
original_timestamp
storage_bucket / storage_key
mime_type
created_at
============================  ===========================================

``tests/unit/test_manifest.py`` asserts both halves of that table: mutating a
committed field changes the entry hash, mutating an excluded one does not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.anchoring.merkle import leaf_hash
from app.core.timeutil import isoformat

#: Bumped only when the serialization rules change. Old entries keep their
#: version so historical proofs continue to verify.
MANIFEST_VERSION = "1"


class EntryType(StrEnum):
    EVIDENCE_MANIFEST = "EVIDENCE_MANIFEST"
    AUDIT_CHECKPOINT = "AUDIT_CHECKPOINT"


#: Evidence columns committed to the log. Order is irrelevant (keys are sorted
#: at serialization time); membership is not.
COMMITTED_EVIDENCE_FIELDS: tuple[str, ...] = (
    "evidence_id",
    "tenant_id",
    "case_id",
    "sha256",
    "size",
    "original_filename",
    "original_path",
    "source",
    "source_type",
    "collector",
    "acquisition_method",
    "collection_timestamp",
    "original_timestamp",
    "storage_bucket",
    "storage_key",
    "mime_type",
    "created_at",
)

#: Explicitly *not* committed, because TRACE may legitimately change them.
EXCLUDED_EVIDENCE_FIELDS: tuple[str, ...] = (
    "legal_hold",
    "retention_policy",
    "parse_status",
    "parse_detail",
    "last_verified_at",
    "last_verification_result",
    "notes",
    "mime_type_source",
    # A measurement of the source machine's clock, revisable when a better
    # one arrives. The original timestamps it applies to are committed; the
    # correction applied to them is analysis (docs/ANCHORING.md §4).
    "clock_offset_seconds",
    "clock_offset_confidence",
    "clock_offset_method",
)


def canonical_json(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON: sorted keys, no insignificant whitespace, UTF-8.

    Floats are refused outright — their textual representation is not stable
    enough to hash. Every numeric field in a manifest is an integer.
    """
    _reject_floats(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise TypeError(f"Float at {path}: manifests must not contain floating point values")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One entry in a transparency log."""

    entry_type: EntryType
    body: dict[str, Any]
    manifest_version: str = MANIFEST_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "entry_type": str(self.entry_type),
            "body": self.body,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.to_payload())

    def entry_hash(self) -> str:
        """SHA-256 of the canonical bytes — a human-facing identifier.

        Distinct from the Merkle leaf hash, which is domain-separated with the
        0x00 prefix. Both are recorded; only the leaf hash enters the tree.
        """
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def merkle_leaf(self) -> bytes:
        return leaf_hash(self.canonical_bytes())


def _timestamp(value: datetime | None) -> str | None:
    return isoformat(value)


def evidence_manifest(evidence: Any) -> LogEntry:
    """Build the log entry for an evidence object.

    Accepts the ORM model or any object exposing the committed attributes.
    """
    body: dict[str, Any] = {}
    for field in COMMITTED_EVIDENCE_FIELDS:
        value = getattr(evidence, field)
        if isinstance(value, datetime):
            value = _timestamp(value)
        elif isinstance(value, bool):  # pragma: no cover - no bool fields committed today
            value = int(value)
        body[field] = value

    missing = [field for field in ("evidence_id", "sha256", "size") if body.get(field) is None]
    if missing:
        raise ValueError(f"Evidence is missing required manifest field(s): {', '.join(missing)}")

    return LogEntry(entry_type=EntryType.EVIDENCE_MANIFEST, body=body)


def audit_checkpoint(
    *, tenant_id: str, sequence: int, record_hash: str, record_count: int
) -> LogEntry:
    """Commit the head of the chain-of-custody chain to the transparency log.

    The audit chain already makes tampering detectable *within* TRACE
    (ADR-0006). Anchoring its head externally makes it detectable even when
    whoever runs TRACE is the one doing the tampering.
    """
    return LogEntry(
        entry_type=EntryType.AUDIT_CHECKPOINT,
        body={
            "tenant_id": tenant_id,
            "sequence": sequence,
            "record_hash": record_hash,
            "record_count": record_count,
        },
    )
