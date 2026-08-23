"""Anchor backend interface.

An *anchor* publishes a signed Merkle root somewhere TRACE cannot retroactively
edit. What that buys depends entirely on the backend, and TRACE reports the
difference rather than blurring it:

===================  =======================================================
Backend              What an anchor there actually proves
===================  =======================================================
``local``            Internal consistency only. The ledger is append-only and
                     hash-chained, but TRACE operates it — a sufficiently
                     privileged operator could rebuild it. Useful as a
                     tamper-evident default and for air-gapped deployments.
                     **Self-attested; not independent evidence.**
``opentimestamps``   Existence before a Bitcoin block. Independent of TRACE
                     and of any single company. Confirmation takes hours.
``evm``              Existence before a block on an EVM chain, attributable to
                     the sending address. Costs gas; confirmation in minutes.
``file``             Nothing on its own. Exports a signed receipt for an
                     external notary, a WORM store, or a court bundle.
===================  =======================================================

``independence`` on each backend records this, and it is surfaced through the
API and UI so nobody mistakes a local anchor for a blockchain one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AnchorStatus(StrEnum):
    PENDING = "PENDING"
    #: Accepted by the backend, not yet durably confirmed (e.g. unconfirmed tx).
    SUBMITTED = "SUBMITTED"
    #: Durably recorded — mined and confirmed, or written to the ledger.
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class Independence(StrEnum):
    """How much of the guarantee survives TRACE itself being compromised."""

    #: TRACE operates the store; proves internal consistency only.
    SELF_ATTESTED = "SELF_ATTESTED"
    #: Recorded by a third party TRACE does not control.
    THIRD_PARTY = "THIRD_PARTY"
    #: Recorded on a public permissionless chain.
    PUBLIC_BLOCKCHAIN = "PUBLIC_BLOCKCHAIN"


@dataclass(slots=True)
class AnchorReceipt:
    """The backend's evidence that the root was published."""

    #: Backend-specific handle: a tx hash, a ledger sequence, a calendar URI.
    external_ref: str
    status: AnchorStatus
    #: Opaque bytes to store verbatim (an .ots file, a signed receipt).
    payload: bytes | None = None
    #: Human-facing location a reviewer can check.
    explorer_url: str | None = None
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnchorVerification:
    verified: bool
    status: AnchorStatus
    detail: str
    external_ref: str | None = None
    anchored_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AnchorBackendError(Exception):
    """The backend could not complete the operation."""


class AnchorBackend(ABC):
    """Publishes a 32-byte root and later proves it was published.

    Implementations receive **only the root hash and the signed tree head** —
    never evidence bytes, filenames, case identifiers or any other content.
    That constraint is the whole reason anchoring is safe to do publicly, and
    it is asserted in ``tests/unit/test_anchor_backends.py``.
    """

    name: str
    independence: Independence
    #: False when the backend needs credentials/network it may not have.
    always_available: bool = False

    @abstractmethod
    async def available(self) -> tuple[bool, str]:
        """Return ``(usable, reason)``. Never raises."""

    @abstractmethod
    async def submit(self, root_hash: str, sth: dict[str, Any]) -> AnchorReceipt:
        """Publish ``root_hash``. ``sth`` is the signed tree head, for context."""

    @abstractmethod
    async def check(self, receipt: AnchorReceipt) -> AnchorVerification:
        """Refresh the status of a previous submission."""

    @abstractmethod
    async def verify(self, root_hash: str, receipt: AnchorReceipt) -> AnchorVerification:
        """Confirm the receipt really commits to ``root_hash``."""

    def explorer_url(self, external_ref: str) -> str | None:  # noqa: ARG002
        return None
