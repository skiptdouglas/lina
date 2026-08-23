"""Evidence manifests: canonical, deterministic, and committed to the right fields."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.anchoring.manifest import (
    COMMITTED_EVIDENCE_FIELDS,
    EXCLUDED_EVIDENCE_FIELDS,
    EntryType,
    LogEntry,
    audit_checkpoint,
    canonical_json,
    evidence_manifest,
)
from app.anchoring.merkle import leaf_hash
from app.evidence.models import Evidence


def make_evidence(**overrides) -> Evidence:
    defaults = dict(
        evidence_id="EVD-0123456789abcdef0123456789abcdef",
        tenant_id="default",
        case_id="CASE-DEMO-001",
        source="FINANCE-LAPTOP-07",
        source_type="SYSMON",
        original_filename="sysmon.jsonl",
        original_path="C:\\Windows\\System32\\winevt\\Logs\\Sysmon.evtx",
        collection_timestamp=datetime(2026, 8, 20, 8, 41, tzinfo=UTC),
        original_timestamp=datetime(2026, 8, 20, 8, 40, tzinfo=UTC),
        collector="manual-upload/1.0",
        acquisition_method="LOG_EXPORT",
        size=4096,
        sha256="a" * 64,
        mime_type="application/json",
        mime_type_source="declared",
        storage_bucket="trace-evidence",
        storage_key="default/CASE-DEMO-001/EVD-x/sysmon.jsonl",
        retention_policy="default-365d",
        legal_hold=False,
        parse_status="QUEUED",
        parse_detail="Queued.",
        last_verified_at=None,
        last_verification_result=None,
        notes=None,
        created_at=datetime(2026, 8, 20, 8, 42, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Evidence(**defaults)


# --------------------------------------------------------------------------
# Canonical serialization
# --------------------------------------------------------------------------
def test_canonical_json_sorts_keys_and_strips_whitespace() -> None:
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json_is_stable_across_dict_ordering() -> None:
    first = canonical_json({"z": 1, "a": {"y": 2, "b": 3}})
    second = canonical_json({"a": {"b": 3, "y": 2}, "z": 1})
    assert first == second


def test_canonical_json_preserves_unicode_without_escaping() -> None:
    assert canonical_json({"k": "café"}) == '{"k":"café"}'.encode()


def test_canonical_json_refuses_floats() -> None:
    """Float formatting is not stable enough to hash."""
    with pytest.raises(TypeError, match="Float at"):
        canonical_json({"size": 1.5})
    with pytest.raises(TypeError, match=r"Float at \$.a\[0\]"):
        canonical_json({"a": [1.5]})
    with pytest.raises(TypeError, match=r"Float at \$.a.b"):
        canonical_json({"a": {"b": 2.5}})


def test_entry_hash_and_leaf_hash_are_different_constructions() -> None:
    entry = LogEntry(EntryType.EVIDENCE_MANIFEST, {"a": 1})
    import hashlib

    assert entry.entry_hash() == hashlib.sha256(entry.canonical_bytes()).hexdigest()
    assert entry.merkle_leaf() == leaf_hash(entry.canonical_bytes())
    assert entry.entry_hash() != entry.merkle_leaf().hex()


# --------------------------------------------------------------------------
# What is and is not committed
# --------------------------------------------------------------------------
def test_manifest_commits_exactly_the_documented_fields() -> None:
    manifest = evidence_manifest(make_evidence())
    assert set(manifest.body) == set(COMMITTED_EVIDENCE_FIELDS)
    for excluded in EXCLUDED_EVIDENCE_FIELDS:
        assert excluded not in manifest.body


@pytest.mark.parametrize("field", COMMITTED_EVIDENCE_FIELDS)
def test_changing_a_committed_field_changes_the_hash(field: str) -> None:
    baseline = evidence_manifest(make_evidence()).entry_hash()
    original = getattr(make_evidence(), field)
    replacement = "MUTATED" if not isinstance(original, int) else original + 1
    if isinstance(original, datetime):
        replacement = datetime(2001, 1, 1, tzinfo=UTC)
    mutated = evidence_manifest(make_evidence(**{field: replacement})).entry_hash()
    assert mutated != baseline, f"{field} is committed but did not affect the hash"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("legal_hold", True),
        ("retention_policy", "hold-7y"),
        ("parse_status", "PARSED"),
        ("parse_detail", "parsed 1200 events"),
        ("last_verified_at", datetime(2027, 1, 1, tzinfo=UTC)),
        ("last_verification_result", "VERIFIED"),
        ("notes", "analyst note added later"),
        ("mime_type_source", "extension"),
    ],
)
def test_changing_a_mutable_field_does_not_break_existing_proofs(field, value) -> None:
    """The property the whole design depends on.

    Flipping a legal hold or parsing an artifact must not invalidate every
    proof issued before it.
    """
    baseline = evidence_manifest(make_evidence()).entry_hash()
    assert evidence_manifest(make_evidence(**{field: value})).entry_hash() == baseline


def test_manifest_is_byte_identical_across_rebuilds() -> None:
    first = evidence_manifest(make_evidence()).canonical_bytes()
    second = evidence_manifest(make_evidence()).canonical_bytes()
    assert first == second


def test_manifest_carries_a_version() -> None:
    payload = json.loads(evidence_manifest(make_evidence()).canonical_bytes())
    assert payload["manifest_version"] == "1"
    assert payload["entry_type"] == "EVIDENCE_MANIFEST"


def test_manifest_timestamps_are_rfc3339_utc() -> None:
    body = evidence_manifest(make_evidence()).body
    assert body["collection_timestamp"] == "2026-08-20T08:41:00Z"
    assert body["created_at"] == "2026-08-20T08:42:00Z"


def test_manifest_requires_the_digest() -> None:
    with pytest.raises(ValueError, match="missing required manifest field"):
        evidence_manifest(make_evidence(sha256=None))


def test_audit_checkpoint_entry() -> None:
    entry = audit_checkpoint(
        tenant_id="default", sequence=12, record_hash="b" * 64, record_count=12
    )
    assert entry.entry_type == EntryType.AUDIT_CHECKPOINT
    assert entry.body["sequence"] == 12
    assert entry.entry_hash() != audit_checkpoint(
        tenant_id="default", sequence=13, record_hash="b" * 64, record_count=13
    ).entry_hash()
