"""Append-only local ledger.

The default backend, and the honest one: it makes tampering *evident* without
pretending to be independent. Each entry chains to its predecessor exactly as
the chain-of-custody records do (ADR-0006), so removing or editing an anchor
breaks every entry after it.

What it does **not** do is survive a compromise of TRACE itself — whoever runs
the platform could rebuild the whole chain. That is precisely why external
backends exist, and why :class:`Independence` is reported alongside every
anchor rather than left to the reader to infer.

Its real value: it works offline. Air-gapped forensic deployments cannot reach
a calendar server or an RPC endpoint, and for them a tamper-evident local
ledger plus periodic manual export is the achievable guarantee.

**Request-scoped by design.** Unlike the external backends this one writes to
TRACE's own database, so it is constructed per request with the *caller's*
session. Two reasons: the ledger entry and the anchor row must commit or roll
back together, and opening a second connection while the request transaction
is open deadlocks on SQLite.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anchoring.backends.base import (
    AnchorBackend,
    AnchorReceipt,
    AnchorStatus,
    AnchorVerification,
    Independence,
)
from app.anchoring.models import LedgerEntry
from app.core.timeutil import isoformat, utcnow

GENESIS = "0" * 64


def ledger_entry_hash(sequence: int, root_hash: str, timestamp: str, prev_hash: str) -> str:
    material = json.dumps(
        {
            "sequence": sequence,
            "root_hash": root_hash,
            "timestamp": timestamp,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LocalLedgerAnchorBackend(AnchorBackend):
    name = "local"
    independence = Independence.SELF_ATTESTED
    always_available = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def available(self) -> tuple[bool, str]:
        return True, "Local append-only ledger (self-attested, works offline)."

    async def submit(self, root_hash: str, sth: dict[str, Any]) -> AnchorReceipt:
        head = (
            await self._session.execute(
                select(LedgerEntry).order_by(LedgerEntry.sequence.desc()).limit(1)
            )
        ).scalars().first()
        sequence = (head.sequence + 1) if head else 1
        prev_hash = head.entry_hash if head else GENESIS
        moment = utcnow()
        timestamp = isoformat(moment) or ""
        entry_hash = ledger_entry_hash(sequence, root_hash, timestamp, prev_hash)

        # Added to the caller's transaction; committed by AnchoringService so the
        # ledger entry and the anchor row are atomic.
        self._session.add(
            LedgerEntry(
                sequence=sequence,
                root_hash=root_hash,
                log_id=str(sth.get("log_id", "")),
                tree_size=int(sth.get("tree_size", 0)),
                timestamp=moment,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
        )
        await self._session.flush()

        return AnchorReceipt(
            external_ref=f"local:{sequence}",
            status=AnchorStatus.CONFIRMED,
            payload=json.dumps(
                {
                    "ledger": "trace-local",
                    "sequence": sequence,
                    "root_hash": root_hash,
                    "timestamp": timestamp,
                    "prev_hash": prev_hash,
                    "entry_hash": entry_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            detail=(
                "Recorded in the local append-only ledger. Self-attested: it proves "
                "internal consistency, not independent existence."
            ),
            metadata={"sequence": sequence, "entry_hash": entry_hash},
        )

    async def check(self, receipt: AnchorReceipt) -> AnchorVerification:
        entry = await self._load(receipt.external_ref)
        if entry is None:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Ledger entry not found — the local ledger has been altered.",
                external_ref=receipt.external_ref,
            )
        return AnchorVerification(
            verified=True,
            status=AnchorStatus.CONFIRMED,
            detail="Present in the local ledger.",
            external_ref=receipt.external_ref,
            anchored_at=isoformat(entry.timestamp),
        )

    async def verify(self, root_hash: str, receipt: AnchorReceipt) -> AnchorVerification:
        entry = await self._load(receipt.external_ref)
        if entry is None:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Ledger entry not found.",
                external_ref=receipt.external_ref,
            )
        if entry.root_hash != root_hash:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Ledger entry commits to a different root hash.",
                external_ref=receipt.external_ref,
            )
        recomputed = ledger_entry_hash(
            entry.sequence, entry.root_hash, isoformat(entry.timestamp) or "", entry.prev_hash
        )
        if recomputed != entry.entry_hash:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Ledger entry hash does not match its contents — it has been edited.",
                external_ref=receipt.external_ref,
            )
        return AnchorVerification(
            verified=True,
            status=AnchorStatus.CONFIRMED,
            detail=(
                "Ledger entry commits to this root and its hash chain is intact. "
                "Self-attested by TRACE."
            ),
            external_ref=receipt.external_ref,
            anchored_at=isoformat(entry.timestamp),
            metadata={"sequence": entry.sequence},
        )

    async def verify_chain(self) -> AnchorVerification:
        """Recompute every link in the ledger."""
        entries = list(
            (
                await self._session.execute(select(LedgerEntry).order_by(LedgerEntry.sequence))
            ).scalars().all()
        )
        prev = GENESIS
        for expected_sequence, entry in enumerate(entries, start=1):
            if entry.sequence != expected_sequence:
                return AnchorVerification(
                    verified=False,
                    status=AnchorStatus.FAILED,
                    detail=f"Ledger is missing entries around sequence {expected_sequence}.",
                )
            if entry.prev_hash != prev:
                return AnchorVerification(
                    verified=False,
                    status=AnchorStatus.FAILED,
                    detail=f"Ledger chain breaks at sequence {entry.sequence}.",
                )
            recomputed = ledger_entry_hash(
                entry.sequence, entry.root_hash, isoformat(entry.timestamp) or "", entry.prev_hash
            )
            if recomputed != entry.entry_hash:
                return AnchorVerification(
                    verified=False,
                    status=AnchorStatus.FAILED,
                    detail=f"Ledger entry {entry.sequence} has been edited.",
                )
            prev = entry.entry_hash
        return AnchorVerification(
            verified=True,
            status=AnchorStatus.CONFIRMED,
            detail=f"All {len(entries)} ledger entr(ies) verified.",
        )

    async def _load(self, external_ref: str) -> LedgerEntry | None:
        if not external_ref.startswith("local:"):
            return None
        try:
            sequence = int(external_ref.split(":", 1)[1])
        except (ValueError, IndexError):
            return None
        return (
            await self._session.execute(
                select(LedgerEntry).where(LedgerEntry.sequence == sequence)
            )
        ).scalars().first()
