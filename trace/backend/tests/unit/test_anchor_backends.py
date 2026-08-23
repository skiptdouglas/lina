"""Anchor backends: what each publishes, and what it refuses to claim."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.anchoring.backends.base import AnchorReceipt, AnchorStatus, Independence
from app.anchoring.backends.evm import CALLDATA_MAGIC, EvmAnchorBackend
from app.anchoring.backends.file_receipt import FileReceiptAnchorBackend
from app.anchoring.backends.local_ledger import (
    GENESIS,
    LocalLedgerAnchorBackend,
    ledger_entry_hash,
)
from app.anchoring.backends.opentimestamps_backend import (
    OpenTimestampsAnchorBackend,
    deserialize_detached,
    serialize_detached,
    summarise_attestations,
)

ROOT = hashlib.sha256(b"a tree root").hexdigest()
STH = {"log_id": "default:evidence", "tree_size": 4, "root_hash": ROOT}


# --------------------------------------------------------------------------
# The constraint that makes anchoring safe to do publicly
# --------------------------------------------------------------------------
def test_backends_receive_only_a_root_and_a_tree_head() -> None:
    """No backend may be handed evidence content.

    ``submit`` takes a hex root and the signed tree head — nothing else. If
    this signature ever grows an evidence or case parameter, publishing it to
    a public chain would leak investigation metadata (ADR-0007).
    """
    import inspect

    from app.anchoring.backends.base import AnchorBackend

    parameters = list(inspect.signature(AnchorBackend.submit).parameters)
    assert parameters == ["self", "root_hash", "sth"]


# --------------------------------------------------------------------------
# Local ledger
# --------------------------------------------------------------------------
async def test_local_ledger_chains_entries(database) -> None:
    async with database.session_factory() as session:
        backend = LocalLedgerAnchorBackend(session)
        first = await backend.submit(ROOT, STH)
        second = await backend.submit("b" * 64, {**STH, "tree_size": 5})
        await session.commit()

        assert first.status == AnchorStatus.CONFIRMED
        assert first.external_ref == "local:1"
        assert second.external_ref == "local:2"

        body_one = json.loads(first.payload)
        body_two = json.loads(second.payload)
        assert body_one["prev_hash"] == GENESIS
        assert body_two["prev_hash"] == body_one["entry_hash"]

        assert (await backend.verify_chain()).verified is True


async def test_local_ledger_reports_itself_as_self_attested(database) -> None:
    async with database.session_factory() as session:
        backend = LocalLedgerAnchorBackend(session)
        assert backend.independence == Independence.SELF_ATTESTED
        receipt = await backend.submit(ROOT, STH)
        await session.commit()
        assert "self-attested" in receipt.detail.lower()
        result = await backend.verify(ROOT, receipt)
        assert result.verified is True
        assert "self-attested" in result.detail.lower()


async def test_local_ledger_detects_an_edited_entry(database) -> None:
    from sqlalchemy import select

    from app.anchoring.models import LedgerEntry

    async with database.session_factory() as session:
        backend = LocalLedgerAnchorBackend(session)
        receipt = await backend.submit(ROOT, STH)
        await session.commit()

        entry = (await session.execute(select(LedgerEntry))).scalars().one()
        entry.root_hash = "c" * 64
        await session.commit()

        assert (await backend.verify(ROOT, receipt)).verified is False
        assert (await backend.verify_chain()).verified is False


async def test_local_ledger_detects_a_deleted_entry(database) -> None:
    from sqlalchemy import select

    from app.anchoring.models import LedgerEntry

    async with database.session_factory() as session:
        backend = LocalLedgerAnchorBackend(session)
        await backend.submit(ROOT, STH)
        await backend.submit("d" * 64, {**STH, "tree_size": 5})
        await backend.submit("e" * 64, {**STH, "tree_size": 6})
        await session.commit()

        middle = (
            await session.execute(select(LedgerEntry).where(LedgerEntry.sequence == 2))
        ).scalars().one()
        await session.delete(middle)
        await session.commit()

        result = await backend.verify_chain()
        assert result.verified is False
        assert "missing entries" in result.detail


async def test_local_ledger_verify_rejects_a_root_mismatch(database) -> None:
    async with database.session_factory() as session:
        backend = LocalLedgerAnchorBackend(session)
        receipt = await backend.submit(ROOT, STH)
        await session.commit()
        result = await backend.verify("f" * 64, receipt)
        assert result.verified is False
        assert "different root hash" in result.detail


def test_ledger_entry_hash_is_deterministic() -> None:
    args = (1, ROOT, "2026-08-23T00:00:00Z", GENESIS)
    assert ledger_entry_hash(*args) == ledger_entry_hash(*args)
    assert ledger_entry_hash(*args) != ledger_entry_hash(2, ROOT, "2026-08-23T00:00:00Z", GENESIS)


# --------------------------------------------------------------------------
# File receipt
# --------------------------------------------------------------------------
async def test_file_receipt_writes_a_file_and_refuses_to_call_it_confirmed(tmp_path) -> None:
    backend = FileReceiptAnchorBackend(str(tmp_path))
    usable, _ = await backend.available()
    assert usable

    receipt = await backend.submit(ROOT, STH)
    assert receipt.status == AnchorStatus.SUBMITTED  # not CONFIRMED: a file is not an anchor
    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1

    body = json.loads(written[0].read_text())
    assert body["root_hash"] == ROOT
    assert "independent party" in body["note"]

    result = await backend.verify(ROOT, receipt)
    assert result.verified is False
    assert "not independent evidence" in result.detail


async def test_file_receipt_detects_a_root_mismatch(tmp_path) -> None:
    backend = FileReceiptAnchorBackend(str(tmp_path))
    receipt = await backend.submit(ROOT, STH)
    assert (await backend.verify("0" * 64, receipt)).verified is False


# --------------------------------------------------------------------------
# OpenTimestamps — offline behaviour
# --------------------------------------------------------------------------
def _ots_receipt(root_hex: str, *, confirmed: bool = False) -> AnchorReceipt:
    """Build a real .ots payload locally, without touching a calendar."""
    from opentimestamps.core.notary import (
        BitcoinBlockHeaderAttestation,
        PendingAttestation,
    )
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

    timestamp = Timestamp(bytes.fromhex(root_hex))
    if confirmed:
        timestamp.attestations.add(BitcoinBlockHeaderAttestation(862_000))
    else:
        timestamp.attestations.add(PendingAttestation("https://alice.btc.calendar.test"))
    payload = serialize_detached(DetachedTimestampFile(OpSHA256(), timestamp))
    return AnchorReceipt(
        external_ref=f"ots:{root_hex}",
        status=AnchorStatus.SUBMITTED,
        payload=payload,
    )


async def test_opentimestamps_reports_available_with_the_reference_library() -> None:
    backend = OpenTimestampsAnchorBackend()
    usable, detail = await backend.available()
    assert usable is True
    assert "calendar server" in detail
    assert backend.independence == Independence.PUBLIC_BLOCKCHAIN


async def test_opentimestamps_verifies_that_a_receipt_commits_to_the_root() -> None:
    backend = OpenTimestampsAnchorBackend()
    result = await backend.verify(ROOT, _ots_receipt(ROOT, confirmed=True))
    assert result.verified is True
    assert "862000" in result.detail
    assert "Bitcoin node" in result.detail  # the limit is stated, not glossed over


async def test_opentimestamps_rejects_a_receipt_for_a_different_root() -> None:
    backend = OpenTimestampsAnchorBackend()
    result = await backend.verify("a" * 64, _ots_receipt(ROOT, confirmed=True))
    assert result.verified is False
    assert "different digest" in result.detail


async def test_opentimestamps_pending_receipt_is_not_reported_as_verified() -> None:
    backend = OpenTimestampsAnchorBackend()
    result = await backend.verify(ROOT, _ots_receipt(ROOT, confirmed=False))
    assert result.verified is False
    assert result.status == AnchorStatus.SUBMITTED
    assert "no Bitcoin attestation yet" in result.detail


async def test_opentimestamps_handles_a_corrupt_receipt_without_raising() -> None:
    backend = OpenTimestampsAnchorBackend()
    result = await backend.verify(
        ROOT, AnchorReceipt(external_ref="ots:x", status=AnchorStatus.SUBMITTED, payload=b"junk")
    )
    assert result.verified is False
    assert "could not be parsed" in result.detail


async def test_opentimestamps_submit_refuses_a_non_32_byte_digest() -> None:
    from app.anchoring.backends.base import AnchorBackendError

    backend = OpenTimestampsAnchorBackend()
    with pytest.raises(AnchorBackendError, match="32 bytes"):
        await backend.submit("abcd", STH)


async def test_opentimestamps_submit_fails_loudly_when_no_calendar_responds() -> None:
    """Egress being blocked must surface as a failure, never a fake receipt."""
    from app.anchoring.backends.base import AnchorBackendError

    backend = OpenTimestampsAnchorBackend(
        calendars=("http://127.0.0.1:1/unreachable",), timeout=1
    )
    with pytest.raises(AnchorBackendError, match="No OpenTimestamps calendar"):
        await backend.submit(ROOT, STH)


def test_ots_serialization_round_trips() -> None:
    receipt = _ots_receipt(ROOT, confirmed=True)
    detached = deserialize_detached(receipt.payload)
    assert detached.timestamp.msg == bytes.fromhex(ROOT)
    summary = summarise_attestations(detached.timestamp)
    assert summary["confirmed"] is True
    assert summary["bitcoin_block_heights"] == [862_000]


# --------------------------------------------------------------------------
# EVM
# --------------------------------------------------------------------------
def test_evm_calldata_carries_only_the_magic_and_the_root() -> None:
    backend = EvmAnchorBackend(rpc_url="http://rpc.invalid", private_key="0x" + "11" * 32)
    calldata = backend._calldata(ROOT)  # noqa: SLF001 - asserting the wire format
    assert calldata == CALLDATA_MAGIC + bytes.fromhex(ROOT)
    assert len(calldata) == 36
    assert CALLDATA_MAGIC == b"TRAC"


async def test_evm_reports_unavailable_without_configuration() -> None:
    backend = EvmAnchorBackend(rpc_url="", private_key="")
    usable, detail = await backend.available()
    assert usable is False
    assert "RPC_URL" in detail


async def test_evm_reports_unavailable_when_the_rpc_is_unreachable() -> None:
    backend = EvmAnchorBackend(
        rpc_url="http://127.0.0.1:1/unreachable", private_key="0x" + "11" * 32, timeout=1
    )
    usable, detail = await backend.available()
    assert usable is False
    assert "unreachable" in detail.lower()


def test_evm_explorer_url_for_known_chains() -> None:
    backend = EvmAnchorBackend(
        rpc_url="http://rpc.invalid", private_key="0x" + "11" * 32, chain_id=1
    )
    assert backend.explorer_url("0xabc") == "https://etherscan.io/tx/0xabc"
    unknown = EvmAnchorBackend(
        rpc_url="http://rpc.invalid", private_key="0x" + "11" * 32, chain_id=999999
    )
    assert unknown.explorer_url("0xabc") is None
