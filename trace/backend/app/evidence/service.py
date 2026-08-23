"""Evidence retrieval, integrity verification and download."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import AuditService
from app.core.config import Settings
from app.core.errors import NotFound
from app.core.security import Principal
from app.core.timeutil import utcnow
from app.evidence.enums import VerificationResult
from app.evidence.integrity import HASH_ALGORITHM, hash_stream, hashes_match
from app.evidence.models import Evidence
from app.evidence.schemas import VerificationResponse
from app.evidence.storage import ObjectNotFound, ObjectStore

logger = logging.getLogger(__name__)


class EvidenceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        store: ObjectStore,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.store = store
        self.audit = audit
        self.settings = settings

    async def get(self, evidence_id: str, principal: Principal) -> Evidence:
        evidence = await self.session.get(Evidence, evidence_id)
        if evidence is None or evidence.tenant_id != principal.tenant_id:
            raise NotFound(f"Evidence {evidence_id} not found.")
        return evidence

    async def list(
        self,
        principal: Principal,
        *,
        case_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Evidence], int]:
        stmt = select(Evidence).where(Evidence.tenant_id == principal.tenant_id)
        count_stmt = (
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.tenant_id == principal.tenant_id)
        )
        if case_id:
            stmt = stmt.where(Evidence.case_id == case_id)
            count_stmt = count_stmt.where(Evidence.case_id == case_id)
        stmt = stmt.order_by(Evidence.created_at.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = (await self.session.execute(count_stmt)).scalar_one()
        return rows, total

    async def verify(
        self,
        evidence_id: str,
        principal: Principal,
        *,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> VerificationResponse:
        """Re-read the stored object and compare its digest with the recorded one.

        A failed verification is still recorded — especially a failed one.
        """
        evidence = await self.get(evidence_id, principal)
        actual_hash: str | None = None
        actual_size: int | None = None

        try:
            actual_hash, actual_size = await hash_stream(
                self.store.stream(
                    evidence.storage_bucket,
                    evidence.storage_key,
                    chunk_size=self.settings.evidence_read_chunk_bytes,
                )
            )
        except ObjectNotFound:
            result = VerificationResult.MISSING
            detail = "The stored object is missing from the evidence bucket."
        except Exception as exc:  # noqa: BLE001 - surfaced to the analyst, not swallowed
            logger.error("Verification error for %s: %s", evidence_id, exc)
            result = VerificationResult.ERROR
            detail = f"Verification could not be completed: {exc.__class__.__name__}"
        else:
            if hashes_match(evidence.sha256, actual_hash) and actual_size == evidence.size:
                result = VerificationResult.VERIFIED
                detail = "Recalculated digest matches the digest recorded at collection."
            else:
                result = VerificationResult.MISMATCH
                detail = (
                    "Recalculated digest does NOT match the digest recorded at collection. "
                    "Treat this object as compromised and preserve the discrepancy."
                )

        verified_at = utcnow()
        evidence.last_verified_at = verified_at
        evidence.last_verification_result = result

        await self.audit.record(
            action=AuditAction.VERIFY,
            principal=principal,
            case_id=evidence.case_id,
            evidence_id=evidence.evidence_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={
                "result": str(result),
                "algorithm": HASH_ALGORITHM,
                "expected_hash": evidence.sha256,
                "actual_hash": actual_hash,
                "size_expected": evidence.size,
                "size_actual": actual_size,
            },
        )
        await self.session.commit()
        await self.audit.flush_mirror()

        return VerificationResponse(
            verified=result == VerificationResult.VERIFIED,
            expected_hash=evidence.sha256,
            actual_hash=actual_hash,
            evidence_id=evidence.evidence_id,
            size_expected=evidence.size,
            size_actual=actual_size,
            result=result,
            verified_at=verified_at,
            detail=detail,
        )

    async def open_download(
        self,
        evidence_id: str,
        principal: Principal,
        *,
        reason: str,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[Evidence, AsyncIterator[bytes]]:
        """Audit the access, then return a byte stream of the original object."""
        evidence = await self.get(evidence_id, principal)
        try:
            await self.store.stat(evidence.storage_bucket, evidence.storage_key)
        except ObjectNotFound as exc:
            raise NotFound("The stored object is missing from the evidence bucket.") from exc

        await self.audit.record(
            action=AuditAction.DOWNLOAD,
            principal=principal,
            case_id=evidence.case_id,
            evidence_id=evidence.evidence_id,
            reason=reason,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"sha256": evidence.sha256, "size": evidence.size},
        )
        await self.session.commit()
        await self.audit.flush_mirror()

        stream = self.store.stream(
            evidence.storage_bucket,
            evidence.storage_key,
            chunk_size=self.settings.evidence_read_chunk_bytes,
        )
        return evidence, stream
