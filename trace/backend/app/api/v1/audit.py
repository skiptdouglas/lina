"""Chain-of-custody endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuditDep, require
from app.audit.actions import AuditAction
from app.audit.schemas import AuditList, AuditRecordRead, ChainVerification
from app.core.security import AUDIT_READ, Principal

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditList)
async def list_audit_records(
    audit: AuditDep,
    principal: Annotated[Principal, Depends(require(AUDIT_READ))],
    case_id: Annotated[str | None, Query(max_length=72)] = None,
    evidence_id: Annotated[str | None, Query(max_length=64)] = None,
    action: AuditAction | None = None,
    actor: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditList:
    rows, total = await audit.query(
        principal,
        case_id=case_id,
        evidence_id=evidence_id,
        action=action,
        actor=actor,
        limit=limit,
        offset=offset,
    )
    return AuditList(
        items=[AuditRecordRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/verify-chain", response_model=ChainVerification)
async def verify_chain(
    audit: AuditDep,
    principal: Annotated[Principal, Depends(require(AUDIT_READ))],
) -> ChainVerification:
    """Recompute every link in this tenant's audit chain (ADR-0006)."""
    return await audit.verify_chain(principal)
