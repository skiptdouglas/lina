"""EVM backend — anchors a root in a transaction on an Ethereum-compatible chain.

Suited to deployments that want minutes-not-hours confirmation, or that
already run a permissioned chain. The root goes in the transaction's calldata
of a zero-value self-transfer, so no contract deployment is needed; a chain
with a notary contract can point ``TRACE_ANCHOR_EVM_CONTRACT`` at it instead.

**Only 32 bytes leave the building.** The calldata is
``0x54524143`` (``TRAC``) followed by the raw root. No case identifier, no
evidence identifier, no filename. Anything else would publish investigation
metadata to a permanent public ledger — see ADR-0007.

Cost and privacy trade-offs, stated plainly:

* Every anchor costs gas, so batch: anchor a tree head covering many evidence
  objects rather than one transaction per object.
* The sending address is a permanent, public identifier for "this TRACE
  deployment". On a public chain, anchor cadence leaks activity volume. Use a
  fresh address per deployment, and prefer OpenTimestamps if that matters.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib import request as urlrequest

from app.anchoring.backends.base import (
    AnchorBackend,
    AnchorBackendError,
    AnchorReceipt,
    AnchorStatus,
    AnchorVerification,
    Independence,
)

logger = logging.getLogger(__name__)

#: ASCII "TRAC" — lets an observer identify TRACE anchors without decoding.
CALLDATA_MAGIC = bytes.fromhex("54524143")

EXPLORERS = {
    1: "https://etherscan.io/tx/",
    11155111: "https://sepolia.etherscan.io/tx/",
    137: "https://polygonscan.com/tx/",
    80002: "https://amoy.polygonscan.com/tx/",
    42161: "https://arbiscan.io/tx/",
    8453: "https://basescan.org/tx/",
}


class EvmAnchorBackend(AnchorBackend):
    name = "evm"
    independence = Independence.PUBLIC_BLOCKCHAIN

    def __init__(
        self,
        *,
        rpc_url: str,
        private_key: str,
        chain_id: int | None = None,
        contract_address: str | None = None,
        confirmations: int = 3,
        gas_limit: int = 60_000,
        timeout: int = 20,
    ) -> None:
        self.rpc_url = rpc_url
        self._private_key = private_key
        self.chain_id = chain_id
        self.contract_address = contract_address
        self.confirmations = confirmations
        self.gas_limit = gas_limit
        self.timeout = timeout

    # ---- availability ------------------------------------------------------
    async def available(self) -> tuple[bool, str]:
        try:
            self._account_module()
        except AnchorBackendError as exc:
            return False, str(exc)
        if not self.rpc_url:
            return False, "TRACE_ANCHOR_EVM_RPC_URL is not set."
        if not self._private_key:
            return False, "TRACE_ANCHOR_EVM_PRIVATE_KEY is not set."
        try:
            chain_id = await self._rpc("eth_chainId", [])
        except Exception as exc:  # noqa: BLE001 - availability probe must not raise
            return False, f"RPC endpoint unreachable: {exc.__class__.__name__}: {exc}"
        return True, f"Connected to chain id {int(chain_id, 16)}."

    @staticmethod
    def _account_module():  # noqa: ANN205
        try:
            from eth_account import Account  # noqa: PLC0415

            return Account
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise AnchorBackendError(
                "The 'eth-account' package is not installed; "
                "install it to enable EVM anchoring."
            ) from exc

    # ---- JSON-RPC ----------------------------------------------------------
    async def _rpc(self, method: str, params: list[Any]) -> Any:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

        def _call() -> Any:
            req = urlrequest.Request(  # noqa: S310 - operator-configured RPC endpoint
                self.rpc_url,
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlrequest.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            if "error" in payload:
                raise AnchorBackendError(f"RPC error for {method}: {payload['error']}")
            return payload["result"]

        return await asyncio.to_thread(_call)

    def _calldata(self, root_hash: str) -> bytes:
        return CALLDATA_MAGIC + bytes.fromhex(root_hash)

    # ---- operations --------------------------------------------------------
    async def submit(self, root_hash: str, sth: dict[str, Any]) -> AnchorReceipt:  # noqa: ARG002
        account_module = self._account_module()
        account = account_module.from_key(self._private_key)

        chain_id = self.chain_id or int(await self._rpc("eth_chainId", []), 16)
        nonce = int(await self._rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
        base_fee_hex = await self._rpc("eth_gasPrice", [])
        gas_price = int(base_fee_hex, 16)

        transaction = {
            "to": self.contract_address or account.address,
            "value": 0,
            "gas": self.gas_limit,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": chain_id,
            "data": "0x" + self._calldata(root_hash).hex(),
        }
        signed = account_module.sign_transaction(transaction, self._private_key)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = await self._rpc("eth_sendRawTransaction", ["0x" + raw.hex().removeprefix("0x")])

        return AnchorReceipt(
            external_ref=str(tx_hash),
            status=AnchorStatus.SUBMITTED,
            payload=json.dumps(
                {
                    "chain_id": chain_id,
                    "tx_hash": tx_hash,
                    "from": account.address,
                    "to": transaction["to"],
                    "calldata": transaction["data"],
                    "root_hash": root_hash,
                },
                sort_keys=True,
            ).encode("utf-8"),
            explorer_url=self.explorer_url(str(tx_hash)),
            detail=(
                f"Broadcast on chain {chain_id}. Confirmed after "
                f"{self.confirmations} block(s)."
            ),
            metadata={"chain_id": chain_id, "from": account.address},
        )

    async def check(self, receipt: AnchorReceipt) -> AnchorVerification:
        tx_hash = receipt.external_ref
        try:
            tx_receipt = await self._rpc("eth_getTransactionReceipt", [tx_hash])
        except Exception as exc:  # noqa: BLE001
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.SUBMITTED,
                detail=f"Could not reach the RPC endpoint: {exc.__class__.__name__}",
                external_ref=tx_hash,
            )
        if tx_receipt is None:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.SUBMITTED,
                detail="Transaction is still in the mempool.",
                external_ref=tx_hash,
            )
        if int(tx_receipt.get("status", "0x0"), 16) != 1:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Transaction reverted.",
                external_ref=tx_hash,
            )

        block_number = int(tx_receipt["blockNumber"], 16)
        head = int(await self._rpc("eth_blockNumber", []), 16)
        depth = head - block_number + 1
        confirmed = depth >= self.confirmations
        return AnchorVerification(
            verified=confirmed,
            status=AnchorStatus.CONFIRMED if confirmed else AnchorStatus.SUBMITTED,
            detail=(
                f"Mined in block {block_number} with {depth} confirmation(s)"
                + ("." if confirmed else f"; {self.confirmations} required.")
            ),
            external_ref=tx_hash,
            metadata={"block_number": block_number, "confirmations": depth},
        )

    async def verify(self, root_hash: str, receipt: AnchorReceipt) -> AnchorVerification:
        """Re-read the transaction and confirm its calldata carries this root."""
        tx_hash = receipt.external_ref
        try:
            transaction = await self._rpc("eth_getTransactionByHash", [tx_hash])
        except Exception as exc:  # noqa: BLE001
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.SUBMITTED,
                detail=f"Could not reach the RPC endpoint: {exc.__class__.__name__}",
                external_ref=tx_hash,
            )
        if transaction is None:
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="Transaction not found on this chain.",
                external_ref=tx_hash,
            )

        expected = "0x" + self._calldata(root_hash).hex()
        if (transaction.get("input") or "").lower() != expected.lower():
            return AnchorVerification(
                verified=False,
                status=AnchorStatus.FAILED,
                detail="On-chain calldata does not commit to this root hash.",
                external_ref=tx_hash,
            )
        status = await self.check(receipt)
        return AnchorVerification(
            verified=status.verified,
            status=status.status,
            detail=f"Calldata commits to this root. {status.detail}",
            external_ref=tx_hash,
            metadata=status.metadata,
        )

    def explorer_url(self, external_ref: str) -> str | None:
        if self.chain_id and self.chain_id in EXPLORERS:
            return f"{EXPLORERS[self.chain_id]}{external_ref}"
        return None
