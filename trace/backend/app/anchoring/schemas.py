"""Anchoring API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.anchoring.backends.base import AnchorStatus, Independence


class LogStatus(BaseModel):
    """Current state of a tenant's transparency logs."""

    log_id: str
    tree_size: int
    root_hash: str
    last_anchored_size: int | None
    last_anchored_root: str | None
    last_anchor_id: str | None
    last_anchor_at: datetime | None
    unanchored_entries: int
    audit_log_size: int
    signing_key_id: str
    signing_algorithm: str
    public_key_b64: str
    default_backend: str


class BackendStatus(BaseModel):
    name: str
    independence: Independence
    available: bool
    detail: str
    is_default: bool


class BackendList(BaseModel):
    items: list[BackendStatus]


class AnchorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str | None = Field(
        default=None, description="Backend name; defaults to TRACE_ANCHOR_BACKEND."
    )
    include_audit_checkpoint: bool = Field(
        default=True,
        description="Also commit the current chain-of-custody head to the audit log.",
    )
    force: bool = Field(
        default=False,
        description="Anchor again even if this tree size is already anchored to this backend.",
    )


class AnchorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    anchor_id: str
    log_id: str
    tree_size: int
    root_hash: str
    previous_tree_size: int | None
    previous_root_hash: str | None
    backend: str
    independence: Independence
    status: AnchorStatus
    external_ref: str | None
    explorer_url: str | None
    detail: str
    key_id: str
    algorithm: str
    created_at: datetime
    confirmed_at: datetime | None
    last_checked_at: datetime | None


class AnchorList(BaseModel):
    items: list[AnchorRead]
    total: int
    limit: int
    offset: int


class AnchorVerifyResponse(BaseModel):
    anchor_id: str
    verified: bool
    status: AnchorStatus
    backend: str
    independence: Independence
    detail: str
    root_hash: str
    signature_valid: bool
    root_recomputed: bool
    external_ref: str | None = None
    metadata: dict[str, Any] = {}


class LeafRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    leaf_index: int
    entry_type: str
    entry_hash: str
    leaf_hash: str
    evidence_id: str | None
    case_id: str | None
    created_at: datetime


class LeafList(BaseModel):
    items: list[LeafRead]
    total: int


class ConsistencyResponse(BaseModel):
    """Proof that the log only ever grew between two sizes."""

    log_id: str
    first: int
    second: int
    first_root: str
    second_root: str
    proof: list[str]
    verified: bool
    detail: str


class BundleVerification(BaseModel):
    """Result of re-checking a bundle; each step is reported separately."""

    verified: bool
    evidence_id: str | None
    checks: dict[str, bool]
    failures: list[str]
    detail: str
    caveats: list[str]
