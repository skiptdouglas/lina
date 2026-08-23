"""File receipt backend — export for an external notary or a court bundle.

Writes the signed tree head and its metadata to a file, and claims nothing
beyond that. It is the right backend when the anchoring authority is not a
blockchain at all: a qualified timestamping authority under eIDAS, a WORM
appliance, a notary, or a printed page in a case file.

Deliberately reports ``SUBMITTED`` rather than ``CONFIRMED``: writing a file
is not an anchor. It becomes one when something outside TRACE countersigns or
stores it, and only a human knows when that happened.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.anchoring.backends.base import (
    AnchorBackend,
    AnchorReceipt,
    AnchorStatus,
    AnchorVerification,
    Independence,
)
from app.core.timeutil import isoformat, utcnow


class FileReceiptAnchorBackend(AnchorBackend):
    name = "file"
    independence = Independence.SELF_ATTESTED
    always_available = True

    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)

    async def available(self) -> tuple[bool, str]:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"Receipt directory is not writable: {exc}"
        return True, f"Receipts are written to {self.output_dir}."

    def _receipt_body(self, root_hash: str, sth: dict[str, Any]) -> bytes:
        return json.dumps(
            {
                "receipt_version": "1",
                "issuer": "TRACE",
                "root_hash": root_hash,
                "signed_tree_head": sth,
                "written_at": isoformat(utcnow()),
                "note": (
                    "This file records a signed TRACE tree head. On its own it proves "
                    "only that TRACE asserts this root. It becomes an anchor when an "
                    "independent party timestamps, countersigns or WORM-stores it."
                ),
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")

    async def submit(self, root_hash: str, sth: dict[str, Any]) -> AnchorReceipt:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"trace-sth-{sth.get('tree_size', 0)}-{root_hash[:16]}.json"
        path = self.output_dir / filename
        payload = self._receipt_body(root_hash, sth)
        path.write_bytes(payload)
        return AnchorReceipt(
            external_ref=f"file:{filename}",
            status=AnchorStatus.SUBMITTED,
            payload=payload,
            detail=(
                f"Receipt written to {path}. Not yet an anchor: have it countersigned "
                f"or stored by an independent party, then mark it confirmed."
            ),
            metadata={"path": str(path)},
        )

    async def check(self, receipt: AnchorReceipt) -> AnchorVerification:
        return AnchorVerification(
            verified=False,
            status=AnchorStatus.SUBMITTED,
            detail=(
                "File receipts cannot self-confirm. Confirmation depends on the external "
                "party that timestamped or stored the file."
            ),
            external_ref=receipt.external_ref,
        )

    async def verify(self, root_hash: str, receipt: AnchorReceipt) -> AnchorVerification:
        if not receipt.payload:
            return AnchorVerification(
                verified=False, status=AnchorStatus.FAILED, detail="No receipt payload stored."
            )
        try:
            body = json.loads(receipt.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return AnchorVerification(
                verified=False, status=AnchorStatus.FAILED, detail="Receipt is not valid JSON."
            )
        if body.get("root_hash") != root_hash:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Receipt commits to a different root hash.",
            )
        return AnchorVerification(
            verified=False,
            status=AnchorStatus.SUBMITTED,
            detail=(
                "Receipt commits to this root, but a file written by TRACE is not "
                "independent evidence. Self-attested."
            ),
            external_ref=receipt.external_ref,
        )
