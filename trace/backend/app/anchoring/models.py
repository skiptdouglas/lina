"""Anchoring tables (docs/ANCHORING.md).

Three tables:

* ``merkle_leaves`` — the transparency log itself. Append-only by contract:
  there is no update or delete path anywhere in the application.
* ``anchors`` — signed tree heads and where each was published.
* ``ledger_entries`` — the local append-only ledger backend's chain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.timeutil import utcnow


class MerkleLeaf(Base):
    """One entry in a transparency log.

    ``entry_json`` stores the canonical entry body so a proof bundle can be
    rebuilt — and independently re-hashed — years later, without depending on
    the evidence row still being present or unchanged.
    """

    __tablename__ = "merkle_leaves"
    __table_args__ = (
        UniqueConstraint("log_id", "leaf_index", name="uq_leaf_log_index"),
        Index("ix_leaf_tenant_evidence", "tenant_id", "evidence_id"),
        Index("ix_leaf_entry_hash", "entry_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    leaf_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: SHA-256 of the canonical entry bytes (display / lookup).
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: RFC 6962 leaf hash: SHA-256(0x00 || canonical bytes). This is what the tree uses.
    leaf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(72), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)


class Anchor(Base):
    """A signed tree head plus the record of where it was published."""

    __tablename__ = "anchors"
    __table_args__ = (
        Index("ix_anchor_tenant_created", "tenant_id", "created_at"),
        Index("ix_anchor_log_size", "log_id", "tree_size"),
    )

    anchor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    log_id: Mapped[str] = mapped_column(String(160), nullable=False)

    tree_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_tree_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_root_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: The exact signed payload, so the signature stays verifiable even if the
    #: STH serialization changes in a later version.
    sth_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="ed25519")

    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    independence: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    external_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Base64 of the backend's opaque receipt (e.g. an .ots file).
    receipt_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LedgerEntry(Base):
    """Hash-chained entry in the local (self-attested) anchor ledger."""

    __tablename__ = "ledger_entries"

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    log_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    tree_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
