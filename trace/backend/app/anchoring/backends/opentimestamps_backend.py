"""OpenTimestamps backend — anchors a root to the Bitcoin blockchain.

Chosen as the default external backend because it needs no wallet, no gas and
no account: calendar servers aggregate submissions into a single periodic
Bitcoin transaction, so the marginal cost of anchoring a root is zero.

**The binary format is produced by the reference ``opentimestamps`` library,
not reimplemented here.** A hand-rolled ``.ots`` writer that is subtly wrong
would produce receipts that look valid and verify nowhere — exactly the kind
of fake integration this codebase refuses to ship. If the library is not
installed, the backend reports itself unavailable rather than degrading.

Lifecycle::

    submit()  -> calendars return a pending attestation   -> SUBMITTED
    check()   -> upgrade from the calendars; once the aggregating
                 transaction is mined a BitcoinBlockHeaderAttestation
                 appears                                  -> CONFIRMED

Confirmation takes hours, which is fine: the guarantee is "this root existed
before block N", and that is not weakened by waiting.

**Scope of what TRACE verifies.** TRACE verifies the receipt commits to the
expected root, and reads the attested block height. It does **not** verify
that block against the Bitcoin chain — that needs a Bitcoin node. TRACE says
so in the verification detail rather than implying more than it checked.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from app.anchoring.backends.base import (
    AnchorBackend,
    AnchorBackendError,
    AnchorReceipt,
    AnchorStatus,
    AnchorVerification,
    Independence,
)

logger = logging.getLogger(__name__)

DEFAULT_CALENDARS = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
)


def _library():  # noqa: ANN202 - returns a module bundle
    """Import the reference library, or report why it is unusable."""
    try:
        from opentimestamps.calendar import RemoteCalendar  # noqa: PLC0415
        from opentimestamps.core.notary import (  # noqa: PLC0415
            BitcoinBlockHeaderAttestation,
            PendingAttestation,
        )
        from opentimestamps.core.op import OpSHA256  # noqa: PLC0415
        from opentimestamps.core.serialize import (  # noqa: PLC0415
            BytesDeserializationContext,
            BytesSerializationContext,
        )
        from opentimestamps.core.timestamp import (  # noqa: PLC0415
            DetachedTimestampFile,
            Timestamp,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise AnchorBackendError(
            "The 'opentimestamps' package is not installed; "
            "install it to enable Bitcoin anchoring."
        ) from exc
    return {
        "RemoteCalendar": RemoteCalendar,
        "Timestamp": Timestamp,
        "DetachedTimestampFile": DetachedTimestampFile,
        "OpSHA256": OpSHA256,
        "PendingAttestation": PendingAttestation,
        "BitcoinBlockHeaderAttestation": BitcoinBlockHeaderAttestation,
        "BytesSerializationContext": BytesSerializationContext,
        "BytesDeserializationContext": BytesDeserializationContext,
    }


def serialize_detached(detached: Any) -> bytes:
    ctx = _library()["BytesSerializationContext"]()
    detached.serialize(ctx)
    return ctx.getbytes()


def deserialize_detached(blob: bytes) -> Any:
    lib = _library()
    return lib["DetachedTimestampFile"].deserialize(lib["BytesDeserializationContext"](blob))


def summarise_attestations(timestamp: Any) -> dict[str, Any]:
    """Classify the attestations in a timestamp without touching the network."""
    lib = _library()
    heights: list[int] = []
    pending: list[str] = []
    other = 0
    for _msg, attestation in timestamp.all_attestations():
        if isinstance(attestation, lib["BitcoinBlockHeaderAttestation"]):
            heights.append(int(attestation.height))
        elif isinstance(attestation, lib["PendingAttestation"]):
            uri = attestation.uri
            pending.append(uri.decode() if isinstance(uri, bytes) else str(uri))
        else:
            other += 1
    return {
        "bitcoin_block_heights": sorted(heights),
        "pending_calendars": sorted(pending),
        "other_attestations": other,
        "confirmed": bool(heights),
    }


class OpenTimestampsAnchorBackend(AnchorBackend):
    name = "opentimestamps"
    independence = Independence.PUBLIC_BLOCKCHAIN

    def __init__(
        self,
        calendars: tuple[str, ...] = DEFAULT_CALENDARS,
        *,
        timeout: int = 15,
        min_calendars: int = 1,
    ) -> None:
        self.calendars = calendars
        self.timeout = timeout
        self.min_calendars = min_calendars

    async def available(self) -> tuple[bool, str]:
        try:
            _library()
        except AnchorBackendError as exc:
            return False, str(exc)
        if not self.calendars:
            return False, "No OpenTimestamps calendar servers are configured."
        return True, f"{len(self.calendars)} calendar server(s) configured."

    async def submit(self, root_hash: str, sth: dict[str, Any]) -> AnchorReceipt:  # noqa: ARG002
        lib = _library()
        digest = bytes.fromhex(root_hash)
        if len(digest) != 32:
            raise AnchorBackendError("An OpenTimestamps digest must be 32 bytes.")

        results = await asyncio.gather(
            *(self._submit_one(url, digest) for url in self.calendars),
            return_exceptions=True,
        )

        merged: Any = None
        reached: list[str] = []
        failures: list[str] = []
        for url, result in zip(self.calendars, results, strict=True):
            if isinstance(result, BaseException):
                failures.append(f"{url}: {result.__class__.__name__}: {result}")
                continue
            reached.append(url)
            if merged is None:
                merged = result
            else:
                merged.merge(result)

        if merged is None or len(reached) < self.min_calendars:
            raise AnchorBackendError(
                "No OpenTimestamps calendar could be reached. "
                + " | ".join(failures[:3])
            )

        detached = lib["DetachedTimestampFile"](lib["OpSHA256"](), merged)
        payload = serialize_detached(detached)
        summary = summarise_attestations(merged)

        return AnchorReceipt(
            external_ref=f"ots:{root_hash}",
            status=AnchorStatus.CONFIRMED if summary["confirmed"] else AnchorStatus.SUBMITTED,
            payload=payload,
            detail=(
                f"Submitted to {len(reached)} calendar server(s). A Bitcoin attestation "
                f"appears once the aggregating transaction is mined (typically a few hours)."
            ),
            metadata={
                "calendars_reached": reached,
                "calendars_failed": failures,
                **summary,
            },
        )

    async def _submit_one(self, url: str, digest: bytes) -> Any:
        lib = _library()
        calendar = lib["RemoteCalendar"](url, user_agent="TRACE/0.2")
        return await asyncio.to_thread(calendar.submit, digest, timeout=self.timeout)

    async def check(self, receipt: AnchorReceipt) -> AnchorVerification:
        """Try to upgrade the timestamp from the calendars."""
        if not receipt.payload:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="No OpenTimestamps receipt stored for this anchor.",
                external_ref=receipt.external_ref,
            )
        try:
            detached = deserialize_detached(receipt.payload)
        except Exception as exc:  # noqa: BLE001 - malformed receipt is a result, not a crash
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail=f"Stored receipt could not be parsed: {exc.__class__.__name__}",
                external_ref=receipt.external_ref,
            )

        upgraded = await self._upgrade(detached.timestamp)
        summary = summarise_attestations(detached.timestamp)

        if summary["confirmed"]:
            heights = summary["bitcoin_block_heights"]
            return AnchorVerification(
                verified=True,
                status=AnchorStatus.CONFIRMED,
                detail=(
                    f"Attested in Bitcoin block {heights[0]}. TRACE has not validated that "
                    f"block against the chain — run `ots verify` with a Bitcoin node for an "
                    f"independent check."
                ),
                external_ref=receipt.external_ref,
                metadata={**summary, "upgraded": upgraded},
            )
        return AnchorVerification(
            verified=False,
            status=AnchorStatus.SUBMITTED,
            detail=(
                "Still pending: the calendars have accepted the digest but the aggregating "
                "Bitcoin transaction is not mined yet."
            ),
            external_ref=receipt.external_ref,
            metadata={**summary, "upgraded": upgraded},
        )

    async def _upgrade(self, timestamp: Any) -> bool:
        """Ask each pending calendar for a completed timestamp. Best effort."""
        lib = _library()
        changed = False
        for msg, attestation in list(timestamp.all_attestations()):
            if not isinstance(attestation, lib["PendingAttestation"]):
                continue
            uri = attestation.uri
            url = uri.decode() if isinstance(uri, bytes) else str(uri)
            try:
                calendar = lib["RemoteCalendar"](url, user_agent="TRACE/0.2")
                upgraded = await asyncio.to_thread(
                    calendar.get_timestamp, msg, timeout=self.timeout
                )
            except Exception as exc:  # noqa: BLE001 - calendar being down is normal
                logger.info("OpenTimestamps upgrade from %s failed: %s", url, exc)
                continue
            if upgraded is not None:
                sub = timestamp.ops.get(msg) if hasattr(timestamp, "ops") else None
                target = sub if sub is not None else timestamp
                try:
                    target.merge(upgraded)
                    changed = True
                except Exception as exc:  # noqa: BLE001 - mismatched message
                    logger.info("OpenTimestamps merge failed: %s", exc)
        return changed

    async def verify(self, root_hash: str, receipt: AnchorReceipt) -> AnchorVerification:
        """Offline check that the receipt commits to this exact root."""
        if not receipt.payload:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="No OpenTimestamps receipt stored for this anchor.",
            )
        try:
            detached = deserialize_detached(receipt.payload)
        except Exception as exc:  # noqa: BLE001
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail=f"Receipt could not be parsed: {exc.__class__.__name__}",
            )

        if detached.timestamp.msg != bytes.fromhex(root_hash):
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail=(
                    "The receipt commits to a different digest than this anchor's root hash."
                ),
            )

        summary = summarise_attestations(detached.timestamp)
        if summary["confirmed"]:
            return AnchorVerification(
                verified=True,
                status=AnchorStatus.CONFIRMED,
                detail=(
                    f"Receipt commits to this root and carries a Bitcoin attestation "
                    f"(block {summary['bitcoin_block_heights'][0]}). Validating that block "
                    f"against the chain requires a Bitcoin node."
                ),
                external_ref=receipt.external_ref,
                metadata=summary,
            )
        return AnchorVerification(
            verified=False,
            status=AnchorStatus.SUBMITTED,
            detail=(
                "Receipt commits to this root but has no Bitcoin attestation yet — "
                "the calendars have not published it."
            ),
            external_ref=receipt.external_ref,
            metadata=summary,
        )

    def explorer_url(self, external_ref: str) -> str | None:
        return None

    def receipt_filename(self, anchor_id: str) -> str:
        return f"{anchor_id}.ots"


def encode_receipt(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")
