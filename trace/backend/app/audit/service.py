"""Chain-of-custody service.

Audit records are appended inside the same transaction as the action they
describe, so an action cannot be committed without its audit entry
(fail-closed, docs/SECURITY.md §6).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import REASON_REQUIRED, ActorType, AuditAction
from app.audit.hashing import GENESIS_HASH, compute_record_hash
from app.audit.models import AuditRecord
from app.audit.schemas import ChainVerification
from app.audit.sinks import AuditMirror, NullAuditMirror
from app.core.errors import AuditWriteFailure, ValidationFailure
from app.core.ids import new_audit_id
from app.core.security import Principal
from app.core.timeutil import utcnow

logger = logging.getLogger(__name__)

#: Chain appends are serialized per tenant. Correct for one API replica; a
#: multi-replica deployment needs a shared sequence (ROADMAP: audit-distributed-chain).
_chain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class AuditService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        mirror: AuditMirror | None = None,
        fail_closed: bool = True,
    ) -> None:
        self.session = session
        self.mirror = mirror or NullAuditMirror()
        self.fail_closed = fail_closed
        self._pending: list[AuditRecord] = []

    # ---- writing -----------------------------------------------------------
    async def record(
        self,
        *,
        action: AuditAction,
        principal: Principal,
        case_id: str | None = None,
        evidence_id: str | None = None,
        entity_id: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        actor_type: ActorType = ActorType.USER,
    ) -> AuditRecord:
        """Append a record to the tenant's chain within the current transaction."""
        if action in REASON_REQUIRED and not (reason or "").strip():
            raise ValidationFailure(f"{action} requires a reason.")

        tenant_id = principal.tenant_id
        try:
            async with _chain_locks[tenant_id]:
                head = await self._chain_head(tenant_id)
                sequence = (head.sequence + 1) if head else 1
                prev_hash = head.record_hash if head else GENESIS_HASH
                record = AuditRecord(
                    audit_id=new_audit_id(),
                    tenant_id=tenant_id,
                    sequence=sequence,
                    timestamp=utcnow(),
                    actor=principal.subject,
                    actor_type=actor_type,
                    action=action,
                    case_id=case_id,
                    evidence_id=evidence_id,
                    entity_id=entity_id,
                    source_ip=source_ip,
                    user_agent=(user_agent or "")[:512] or None,
                    reason=reason,
                    details=details or {},
                    prev_hash=prev_hash,
                    record_hash="",
                )
                record.record_hash = compute_record_hash(record, prev_hash)
                self.session.add(record)
                await self.session.flush()
        except ValidationFailure:
            raise
        except Exception as exc:
            logger.error("Audit write failed for action=%s: %s", action, exc)
            if self.fail_closed:
                raise AuditWriteFailure(
                    "The action was rejected because it could not be audited."
                ) from exc
            return AuditRecord(audit_id="", tenant_id=tenant_id, sequence=0, action=action,
                               actor=principal.subject, prev_hash=GENESIS_HASH, record_hash="")

        self._pending.append(record)
        return record

    async def _chain_head(self, tenant_id: str) -> AuditRecord | None:
        stmt = (
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant_id)
            .order_by(AuditRecord.sequence.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def flush_mirror(self) -> None:
        """Emit committed records to the secondary sink. Call after commit."""
        if not self._pending:
            return
        pending, self._pending = self._pending, []
        await self.mirror.emit(pending)

    # ---- reading -----------------------------------------------------------
    async def query(
        self,
        principal: Principal,
        *,
        case_id: str | None = None,
        evidence_id: str | None = None,
        action: AuditAction | None = None,
        actor: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditRecord], int]:
        stmt = select(AuditRecord).where(AuditRecord.tenant_id == principal.tenant_id)
        count_stmt = (
            select(func.count())
            .select_from(AuditRecord)
            .where(AuditRecord.tenant_id == principal.tenant_id)
        )
        filters = []
        if case_id:
            filters.append(AuditRecord.case_id == case_id)
        if evidence_id:
            filters.append(AuditRecord.evidence_id == evidence_id)
        if action:
            filters.append(AuditRecord.action == action)
        if actor:
            filters.append(AuditRecord.actor == actor)
        for condition in filters:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        stmt = stmt.order_by(AuditRecord.sequence.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = (await self.session.execute(count_stmt)).scalar_one()
        return rows, total

    async def verify_chain(self, principal: Principal) -> ChainVerification:
        """Recompute every link and report the first divergence."""
        tenant_id = principal.tenant_id
        stmt = (
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant_id)
            .order_by(AuditRecord.sequence.asc())
        )
        records = list((await self.session.execute(stmt)).scalars().all())

        prev_hash = GENESIS_HASH
        expected_sequence = 1
        missing: list[int] = []
        for record in records:
            while record.sequence > expected_sequence:
                missing.append(expected_sequence)
                expected_sequence += 1
            expected_sequence += 1

            if record.prev_hash != prev_hash:
                return ChainVerification(
                    verified=False,
                    tenant_id=tenant_id,
                    records_checked=len(records),
                    first_broken_sequence=record.sequence,
                    first_broken_audit_id=record.audit_id,
                    missing_sequences=missing,
                    detail="Chain link mismatch: prev_hash does not match the previous record.",
                )
            recomputed = compute_record_hash(record, record.prev_hash)
            if recomputed != record.record_hash:
                return ChainVerification(
                    verified=False,
                    tenant_id=tenant_id,
                    records_checked=len(records),
                    first_broken_sequence=record.sequence,
                    first_broken_audit_id=record.audit_id,
                    missing_sequences=missing,
                    detail="Record hash mismatch: this record's content has changed.",
                )
            prev_hash = record.record_hash

        if missing:
            return ChainVerification(
                verified=False,
                tenant_id=tenant_id,
                records_checked=len(records),
                first_broken_sequence=missing[0],
                missing_sequences=missing,
                detail="Chain is missing records; sequence numbers are not contiguous.",
            )
        return ChainVerification(
            verified=True,
            tenant_id=tenant_id,
            records_checked=len(records),
            missing_sequences=[],
            detail=f"All {len(records)} record(s) verified.",
        )
