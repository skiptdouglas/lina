"""Anchoring orchestration.

    Evidence file -> SHA-256 -> manifest -> Merkle leaf -> tree -> root
                  -> signed by TRACE -> published to an immutable ledger

The first four steps happen on ingest, synchronously and in the same
transaction as the evidence row. The last two happen on a schedule or on
demand, because publishing is slow, sometimes costs money, and batches well:
one anchor covers every entry added since the last one.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anchoring.backends.base import (
    AnchorBackend,
    AnchorBackendError,
    AnchorReceipt,
    AnchorStatus,
    Independence,
)
from app.anchoring.backends.local_ledger import LocalLedgerAnchorBackend
from app.anchoring.bundle import build_bundle
from app.anchoring.log import TransparencyLog, audit_log_id, evidence_log_id
from app.anchoring.manifest import audit_checkpoint, evidence_manifest
from app.anchoring.merkle import verify_consistency, verify_inclusion
from app.anchoring.models import Anchor, MerkleLeaf
from app.anchoring.schemas import (
    AnchorVerifyResponse,
    BundleVerification,
    ConsistencyResponse,
    LogStatus,
)
from app.anchoring.signing import Signer, verify_signature
from app.audit.actions import AuditAction
from app.audit.models import AuditRecord
from app.audit.service import AuditService
from app.core.config import Settings
from app.core.errors import Conflict, NotFound, ValidationFailure
from app.core.ids import _new
from app.core.security import Principal
from app.core.timeutil import isoformat, utcnow

logger = logging.getLogger(__name__)

BUNDLE_CAVEATS = (
    "A passing bundle proves the evidence digest was committed to the log and "
    "that the log was not rewritten below this root. It says nothing about "
    "whether the evidence itself is authentic or lawfully obtained.",
    "The signature attests to custody of the log signing key, not to the identity "
    "of whoever collected the artifact.",
    "Independence depends on the anchor backend: a 'local' anchor is self-attested "
    "by TRACE and is not third-party evidence.",
)


def new_anchor_id() -> str:
    return _new("ANC")


class AnchoringService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        signer: Signer | None,
        backends: dict[str, AnchorBackend],
        audit: AuditService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.signer = signer
        # The local ledger writes to this same database, so it joins this
        # request's transaction rather than opening its own connection.
        self.backends: dict[str, AnchorBackend] = dict(backends)
        if settings.anchor_enabled:
            self.backends.setdefault("local", LocalLedgerAnchorBackend(session))
        self.audit = audit

    # ---- helpers -----------------------------------------------------------
    def _require_signer(self) -> Signer:
        if self.signer is None:
            raise ValidationFailure(
                "Evidence anchoring is not configured: no log signing key is available."
            )
        return self.signer

    def _backend(self, name: str | None) -> AnchorBackend:
        resolved = name or self.settings.anchor_backend
        backend = self.backends.get(resolved)
        if backend is None:
            available = ", ".join(sorted(self.backends)) or "none"
            raise ValidationFailure(
                f"Unknown anchor backend '{resolved}'. Configured backends: {available}."
            )
        return backend

    def evidence_log(self, tenant_id: str) -> TransparencyLog:
        return TransparencyLog(self.session, evidence_log_id(tenant_id))

    def audit_log(self, tenant_id: str) -> TransparencyLog:
        return TransparencyLog(self.session, audit_log_id(tenant_id))

    # ---- appending ---------------------------------------------------------
    async def append_evidence(self, evidence: Any) -> MerkleLeaf:
        """Commit an evidence manifest to the tenant's log.

        Called from ingestion inside the same transaction as the evidence row,
        so an evidence object can never exist without its log entry.
        """
        entry = evidence_manifest(evidence)
        return await self.evidence_log(evidence.tenant_id).append(
            entry,
            tenant_id=evidence.tenant_id,
            evidence_id=evidence.evidence_id,
            case_id=evidence.case_id,
        )

    async def append_audit_checkpoint(self, tenant_id: str) -> MerkleLeaf | None:
        """Commit the current chain-of-custody head to the audit log."""
        head = (
            await self.session.execute(
                select(AuditRecord)
                .where(AuditRecord.tenant_id == tenant_id)
                .order_by(AuditRecord.sequence.desc())
                .limit(1)
            )
        ).scalars().first()
        if head is None:
            return None
        entry = audit_checkpoint(
            tenant_id=tenant_id,
            sequence=head.sequence,
            record_hash=head.record_hash,
            record_count=head.sequence,
        )
        log = self.audit_log(tenant_id)
        latest = await log.leaves(limit=1)
        if latest and latest[0].entry_hash == entry.entry_hash():
            # The chain has not moved since the last checkpoint; adding an
            # identical leaf would inflate the log without adding information.
            return latest[0]
        return await log.append(entry, tenant_id=tenant_id)

    # ---- anchoring ---------------------------------------------------------
    async def create_anchor(
        self,
        principal: Principal,
        *,
        backend_name: str | None = None,
        include_audit_checkpoint: bool = True,
        force: bool = False,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> Anchor:
        signer = self._require_signer()
        backend = self._backend(backend_name)
        tenant_id = principal.tenant_id

        if include_audit_checkpoint:
            await self.append_audit_checkpoint(tenant_id)

        log = self.evidence_log(tenant_id)
        tree_size = await log.size()
        if tree_size == 0:
            raise ValidationFailure(
                "There is nothing to anchor: no evidence has been ingested for this tenant."
            )

        existing = await self._latest_anchor(tenant_id, backend=backend.name)
        if (
            existing is not None
            and existing.tree_size == tree_size
            and existing.status != AnchorStatus.FAILED
            and not force
        ):
            raise Conflict(
                f"Tree size {tree_size} is already anchored to '{backend.name}' "
                f"({existing.anchor_id}). Pass force=true to anchor it again."
            )

        previous = await self._latest_anchor(tenant_id)
        root = (await log.root(tree_size)).hex()
        sth = signer.sign_tree_head(
            log_id=log.log_id,
            tree_size=tree_size,
            root_hash=root,
            previous_tree_size=previous.tree_size if previous else None,
            previous_root_hash=previous.root_hash if previous else None,
        )

        try:
            receipt = await backend.submit(root, sth.signed_payload())
        except AnchorBackendError as exc:
            logger.error("Anchor submission failed on %s: %s", backend.name, exc)
            receipt = AnchorReceipt(
                external_ref="",
                status=AnchorStatus.FAILED,
                detail=f"Submission failed: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - a backend outage is a recorded outcome
            logger.exception("Unexpected anchor backend failure on %s", backend.name)
            receipt = AnchorReceipt(
                external_ref="",
                status=AnchorStatus.FAILED,
                detail=f"Submission failed: {exc.__class__.__name__}: {exc}",
            )

        anchor = Anchor(
            anchor_id=new_anchor_id(),
            tenant_id=tenant_id,
            log_id=log.log_id,
            tree_size=tree_size,
            root_hash=root,
            previous_tree_size=sth.previous_tree_size,
            previous_root_hash=sth.previous_root_hash,
            sth_json=sth.signed_payload(),
            signature=sth.signature,
            key_id=sth.key_id,
            public_key=signer.public_key_b64,
            algorithm=sth.algorithm,
            backend=backend.name,
            independence=str(backend.independence),
            status=str(receipt.status),
            external_ref=receipt.external_ref or None,
            explorer_url=receipt.explorer_url,
            receipt_b64=(
                base64.b64encode(receipt.payload).decode("ascii") if receipt.payload else None
            ),
            detail=receipt.detail,
            created_at=utcnow(),
            confirmed_at=utcnow() if receipt.status == AnchorStatus.CONFIRMED else None,
            last_checked_at=utcnow(),
        )
        self.session.add(anchor)
        await self.session.flush()

        if self.audit is not None:
            await self.audit.record(
                action=AuditAction.ANCHOR,
                principal=principal,
                source_ip=source_ip,
                user_agent=user_agent,
                details={
                    "anchor_id": anchor.anchor_id,
                    "log_id": anchor.log_id,
                    "tree_size": tree_size,
                    "root_hash": root,
                    "backend": backend.name,
                    "independence": str(backend.independence),
                    "status": str(receipt.status),
                    "external_ref": receipt.external_ref,
                },
            )
        await self.session.commit()
        if self.audit is not None:
            await self.audit.flush_mirror()
        return anchor

    async def refresh_anchor(self, anchor_id: str, principal: Principal) -> Anchor:
        """Re-check a submitted anchor with its backend (e.g. did it get mined?)."""
        anchor = await self.get_anchor(anchor_id, principal)
        backend = self._backend(anchor.backend)
        receipt = self._receipt_from(anchor)

        result = await backend.check(receipt)
        anchor.status = str(result.status)
        anchor.detail = result.detail
        anchor.last_checked_at = utcnow()
        if result.status == AnchorStatus.CONFIRMED and anchor.confirmed_at is None:
            anchor.confirmed_at = utcnow()
        await self.session.commit()
        return anchor

    async def verify_anchor(
        self,
        anchor_id: str,
        principal: Principal,
        *,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> AnchorVerifyResponse:
        """Re-derive the root from the log, re-check the signature, re-check the ledger."""
        anchor = await self.get_anchor(anchor_id, principal)
        log = TransparencyLog(self.session, anchor.log_id)

        recomputed = False
        try:
            recomputed = (await log.root(anchor.tree_size)).hex() == anchor.root_hash
        except ValidationFailure:
            recomputed = False

        signature_valid = self._verify_stored_signature(anchor)

        backend = self.backends.get(anchor.backend)
        if backend is None:
            ledger = None
            detail = f"Backend '{anchor.backend}' is not configured on this deployment."
            status = AnchorStatus(anchor.status)
            metadata: dict[str, Any] = {}
        else:
            ledger = await backend.verify(anchor.root_hash, self._receipt_from(anchor))
            detail = ledger.detail
            status = ledger.status
            metadata = ledger.metadata

        verified = bool(recomputed and signature_valid and (ledger.verified if ledger else False))

        if self.audit is not None:
            await self.audit.record(
                action=AuditAction.ANCHOR_VERIFY,
                principal=principal,
                source_ip=source_ip,
                user_agent=user_agent,
                details={
                    "anchor_id": anchor.anchor_id,
                    "verified": verified,
                    "root_recomputed": recomputed,
                    "signature_valid": signature_valid,
                    "backend": anchor.backend,
                },
            )
            await self.session.commit()
            await self.audit.flush_mirror()

        return AnchorVerifyResponse(
            anchor_id=anchor.anchor_id,
            verified=verified,
            status=status,
            backend=anchor.backend,
            independence=Independence(anchor.independence),
            detail=self._compose_verify_detail(recomputed, signature_valid, detail),
            root_hash=anchor.root_hash,
            signature_valid=signature_valid,
            root_recomputed=recomputed,
            external_ref=anchor.external_ref,
            metadata=metadata,
        )

    @staticmethod
    def _compose_verify_detail(recomputed: bool, signature_valid: bool, ledger: str) -> str:
        parts = []
        parts.append(
            "Root recomputed from the log matches the anchor."
            if recomputed
            else "Root recomputed from the log does NOT match the anchor."
        )
        parts.append(
            "Tree-head signature is valid."
            if signature_valid
            else "Tree-head signature is INVALID."
        )
        parts.append(ledger)
        return " ".join(parts)

    def _verify_stored_signature(self, anchor: Anchor) -> bool:
        from app.anchoring.manifest import canonical_json  # noqa: PLC0415
        from app.anchoring.signing import STH_DOMAIN  # noqa: PLC0415

        try:
            public_key = base64.b64decode(anchor.public_key)
            signature = base64.b64decode(anchor.signature)
        except (ValueError, TypeError):
            return False
        payload = STH_DOMAIN + canonical_json(dict(anchor.sth_json))
        return verify_signature(public_key, payload, signature)

    @staticmethod
    def _receipt_from(anchor: Anchor) -> AnchorReceipt:
        return AnchorReceipt(
            external_ref=anchor.external_ref or "",
            status=AnchorStatus(anchor.status),
            payload=base64.b64decode(anchor.receipt_b64) if anchor.receipt_b64 else None,
            explorer_url=anchor.explorer_url,
            detail=anchor.detail,
        )

    # ---- reading -----------------------------------------------------------
    async def get_anchor(self, anchor_id: str, principal: Principal) -> Anchor:
        anchor = await self.session.get(Anchor, anchor_id)
        if anchor is None or anchor.tenant_id != principal.tenant_id:
            raise NotFound(f"Anchor {anchor_id} not found.")
        return anchor

    async def _latest_anchor(self, tenant_id: str, *, backend: str | None = None) -> Anchor | None:
        stmt = (
            select(Anchor)
            .where(Anchor.tenant_id == tenant_id, Anchor.log_id == evidence_log_id(tenant_id))
            .order_by(Anchor.tree_size.desc(), Anchor.created_at.desc())
            .limit(1)
        )
        if backend:
            stmt = stmt.where(Anchor.backend == backend)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_anchors(
        self, principal: Principal, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Anchor], int]:
        base = select(Anchor).where(Anchor.tenant_id == principal.tenant_id)
        rows = list(
            (
                await self.session.execute(
                    base.order_by(Anchor.created_at.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(Anchor).where(
                    Anchor.tenant_id == principal.tenant_id
                )
            )
        ).scalar_one()
        return rows, total

    async def log_status(self, principal: Principal) -> LogStatus:
        signer = self._require_signer()
        tenant_id = principal.tenant_id
        log = self.evidence_log(tenant_id)
        tree_size = await log.size()
        latest = await self._latest_anchor(tenant_id)
        return LogStatus(
            log_id=log.log_id,
            tree_size=tree_size,
            root_hash=(await log.root(tree_size)).hex(),
            last_anchored_size=latest.tree_size if latest else None,
            last_anchored_root=latest.root_hash if latest else None,
            last_anchor_id=latest.anchor_id if latest else None,
            last_anchor_at=latest.created_at if latest else None,
            unanchored_entries=tree_size - (latest.tree_size if latest else 0),
            audit_log_size=await self.audit_log(tenant_id).size(),
            signing_key_id=signer.key_id,
            signing_algorithm=signer.algorithm,
            public_key_b64=signer.public_key_b64,
            default_backend=self.settings.anchor_backend,
        )

    async def consistency(
        self, principal: Principal, first: int, second: int
    ) -> ConsistencyResponse:
        log = self.evidence_log(principal.tenant_id)
        size = await log.size()
        if second > size:
            raise ValidationFailure(f"second={second} exceeds the log size ({size}).")
        if first > second:
            raise ValidationFailure("first must not exceed second.")
        proof = await log.consistency_proof(first, second)
        first_root = (await log.root(first)).hex()
        second_root = (await log.root(second)).hex()
        verified = verify_consistency(
            first,
            second,
            [bytes.fromhex(node) for node in proof],
            bytes.fromhex(first_root),
            bytes.fromhex(second_root),
        )
        return ConsistencyResponse(
            log_id=log.log_id,
            first=first,
            second=second,
            first_root=first_root,
            second_root=second_root,
            proof=proof,
            verified=verified,
            detail=(
                f"The log of size {first} is a prefix of the log of size {second}: "
                f"no entry was removed, reordered or rewritten."
                if verified
                else "Consistency proof FAILED — the log has been rewritten."
            ),
        )

    # ---- proof bundles -----------------------------------------------------
    async def proof_bundle(
        self,
        evidence_id: str,
        principal: Principal,
        *,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Build the self-contained, offline-verifiable bundle for one evidence object."""
        tenant_id = principal.tenant_id
        log = self.evidence_log(tenant_id)
        leaf = await log.leaf_for_evidence(evidence_id)
        if leaf.tenant_id != tenant_id:  # pragma: no cover - log id already scopes this
            raise NotFound(f"Evidence {evidence_id} has no entry in this tenant's log.")

        # Prefer the largest anchored tree that contains this leaf: a bundle
        # against an anchored root is externally checkable, one against the
        # current head is not.
        anchor = await self._anchor_covering(tenant_id, leaf.leaf_index)
        tree_size = anchor.tree_size if anchor else await log.size()

        proof = await log.inclusion_proof(leaf.leaf_index, tree_size)
        root = (await log.root(tree_size)).hex()

        if anchor is not None:
            sth = dict(anchor.sth_json)
            signature = anchor.signature
            key_id = anchor.key_id
            public_key = anchor.public_key
            algorithm = anchor.algorithm
            anchor_block: dict[str, Any] | None = {
                "anchor_id": anchor.anchor_id,
                "backend": anchor.backend,
                "independence": anchor.independence,
                "status": anchor.status,
                "external_ref": anchor.external_ref,
                "explorer_url": anchor.explorer_url,
                "receipt_b64": anchor.receipt_b64,
                "created_at": isoformat(anchor.created_at),
                "confirmed_at": isoformat(anchor.confirmed_at),
                "detail": anchor.detail,
            }
        else:
            # Not yet anchored: sign the current head so the bundle is still
            # signature-verifiable, and say plainly that nothing external
            # backs it yet.
            signer = self._require_signer()
            head = signer.sign_tree_head(
                log_id=log.log_id, tree_size=tree_size, root_hash=root
            )
            sth = head.signed_payload()
            signature = head.signature
            key_id = head.key_id
            public_key = signer.public_key_b64
            algorithm = head.algorithm
            anchor_block = {
                "status": "NOT_ANCHORED",
                "detail": (
                    "This entry is in the log and signed by TRACE, but the tree head "
                    "covering it has not been published to any ledger yet. Until it is, "
                    "the guarantee is self-attested."
                ),
            }

        bundle = build_bundle(
            evidence_id=evidence_id,
            manifest=dict(leaf.entry_json),
            leaf_index=leaf.leaf_index,
            leaf_hash=leaf.leaf_hash,
            entry_hash=leaf.entry_hash,
            tree_size=tree_size,
            root_hash=root,
            inclusion_proof=proof,
            signed_tree_head=sth,
            signature=signature,
            key_id=key_id,
            public_key_b64=public_key,
            algorithm=algorithm,
            anchor=anchor_block,
        )

        if self.audit is not None:
            await self.audit.record(
                action=AuditAction.PROOF_EXPORT,
                principal=principal,
                case_id=leaf.case_id,
                evidence_id=evidence_id,
                source_ip=source_ip,
                user_agent=user_agent,
                details={
                    "leaf_index": leaf.leaf_index,
                    "tree_size": tree_size,
                    "root_hash": root,
                    "anchored": anchor is not None,
                },
            )
            await self.session.commit()
            await self.audit.flush_mirror()

        return bundle

    async def _anchor_covering(self, tenant_id: str, leaf_index: int) -> Anchor | None:
        """The smallest anchored tree that contains this leaf.

        Smallest, not largest: it is the earliest published commitment to the
        entry, which is the strongest claim about *when* it existed.
        """
        stmt = (
            select(Anchor)
            .where(
                Anchor.tenant_id == tenant_id,
                Anchor.log_id == evidence_log_id(tenant_id),
                Anchor.tree_size > leaf_index,
                Anchor.status.in_([AnchorStatus.CONFIRMED, AnchorStatus.SUBMITTED]),
            )
            .order_by(Anchor.tree_size.asc(), Anchor.created_at.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    # ---- bundle verification ----------------------------------------------
    @staticmethod
    def verify_bundle(bundle: dict[str, Any]) -> BundleVerification:
        """Re-check a bundle with no reference to the live log.

        The same logic ``scripts/verify_anchor.py`` runs offline. Offered over
        the API for convenience only — a bundle checked by the system that
        issued it proves less than one checked independently.
        """
        from app.anchoring.manifest import canonical_json  # noqa: PLC0415
        from app.anchoring.merkle import leaf_hash as compute_leaf  # noqa: PLC0415
        from app.anchoring.signing import STH_DOMAIN  # noqa: PLC0415

        checks: dict[str, bool] = {}
        failures: list[str] = []

        try:
            manifest = bundle["manifest"]
            leaf = bundle["leaf"]
            tree = bundle["tree"]
            sth = bundle["signed_tree_head"]
            signature_block = bundle["signature"]
        except (KeyError, TypeError):
            return BundleVerification(
                verified=False,
                evidence_id=None,
                checks={},
                failures=["Bundle is malformed: required sections are missing."],
                detail="Bundle is malformed.",
                caveats=list(BUNDLE_CAVEATS),
            )

        # 1. manifest -> leaf hash
        try:
            recomputed_leaf = compute_leaf(canonical_json(manifest)).hex()
            checks["leaf_hash_matches_manifest"] = recomputed_leaf == leaf.get("leaf_hash")
        except (TypeError, ValueError) as exc:
            checks["leaf_hash_matches_manifest"] = False
            failures.append(f"Manifest could not be canonically serialized: {exc}")
        if not checks.get("leaf_hash_matches_manifest"):
            failures.append("The manifest does not hash to the leaf hash in the bundle.")

        # 2. inclusion proof -> root
        try:
            inclusion_ok = verify_inclusion(
                bytes.fromhex(leaf["leaf_hash"]),
                int(leaf["index"]),
                int(tree["tree_size"]),
                [bytes.fromhex(node) for node in tree["inclusion_proof"]],
                bytes.fromhex(tree["root_hash"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            inclusion_ok = False
            failures.append(f"Inclusion proof is malformed: {exc}")
        checks["inclusion_proof_valid"] = inclusion_ok
        if not inclusion_ok:
            failures.append("The inclusion proof does not reproduce the root hash.")

        # 3. root in the bundle == root in the signed tree head
        root_matches = tree.get("root_hash") == sth.get("root_hash")
        checks["root_matches_signed_tree_head"] = root_matches
        if not root_matches:
            failures.append("The signed tree head commits to a different root hash.")

        # 4. signature over the tree head
        try:
            public_key = base64.b64decode(signature_block["public_key_b64"])
            raw_signature = base64.b64decode(signature_block["value"])
            signature_ok = verify_signature(
                public_key, STH_DOMAIN + canonical_json(sth), raw_signature
            )
        except (KeyError, ValueError, TypeError) as exc:
            signature_ok = False
            failures.append(f"Signature block is malformed: {exc}")
        checks["signature_valid"] = signature_ok
        if not signature_ok:
            failures.append("The tree-head signature does not verify against the public key.")

        anchor = bundle.get("anchor") or {}
        anchored = anchor.get("status") in ("CONFIRMED", "SUBMITTED")
        checks["externally_anchored"] = bool(anchored)
        if not anchored:
            failures.append(
                "The tree head is not published to any ledger, so the timestamp is "
                "self-attested by TRACE."
            )

        verified = all(
            checks.get(key, False)
            for key in (
                "leaf_hash_matches_manifest",
                "inclusion_proof_valid",
                "root_matches_signed_tree_head",
                "signature_valid",
            )
        )
        return BundleVerification(
            verified=verified,
            evidence_id=bundle.get("evidence_id"),
            checks=checks,
            failures=failures,
            detail=(
                "Cryptographic chain intact: manifest -> leaf -> root -> signature."
                if verified
                else "Verification FAILED — see failures."
            ),
            caveats=list(BUNDLE_CAVEATS),
        )
