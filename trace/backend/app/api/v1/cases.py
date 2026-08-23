"""Case endpoints (brief §40)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    AuditDep,
    CaseServiceDep,
    SessionDep,
    client_ip,
    require,
    user_agent,
)
from app.audit.actions import AuditAction
from app.cases.enums import CaseStatus
from app.cases.schemas import CaseCreate, CaseList, CaseRead, CaseUpdate
from app.core.capabilities import not_implemented
from app.core.security import (
    CASE_CREATE,
    CASE_READ,
    CASE_UPDATE,
    Principal,
)

router = APIRouter(prefix="/cases", tags=["cases"])


async def _to_read(case, service: CaseServiceDep) -> CaseRead:  # noqa: ANN001
    payload = CaseRead.model_validate(case)
    payload.counts = await service.counts(case)
    return payload


@router.post("", response_model=CaseRead, status_code=201)
async def create_case(
    payload: CaseCreate,
    request: Request,
    service: CaseServiceDep,
    audit: AuditDep,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require(CASE_CREATE))],
) -> CaseRead:
    case = await service.create(payload, principal)
    await audit.record(
        action=AuditAction.CASE_CREATE,
        principal=principal,
        case_id=case.case_id,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
        details={"title": case.title, "severity": case.severity},
    )
    await session.commit()
    await audit.flush_mirror()
    return await _to_read(case, service)


@router.get("", response_model=CaseList)
async def list_cases(
    service: CaseServiceDep,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    status: CaseStatus | None = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CaseList:
    cases, total = await service.list(
        principal, status=status, query=q, limit=limit, offset=offset
    )
    items = [await _to_read(case, service) for case in cases]
    return CaseList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{case_id}", response_model=CaseRead)
async def get_case(
    case_id: str,
    service: CaseServiceDep,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> CaseRead:
    case = await service.get(case_id, principal)
    return await _to_read(case, service)


@router.patch("/{case_id}", response_model=CaseRead)
async def update_case(
    case_id: str,
    payload: CaseUpdate,
    request: Request,
    service: CaseServiceDep,
    audit: AuditDep,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require(CASE_UPDATE))],
) -> CaseRead:
    case = await service.update(case_id, payload, principal)
    await audit.record(
        action=AuditAction.CASE_UPDATE,
        principal=principal,
        case_id=case.case_id,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
        details={"changed": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    await session.commit()
    await audit.flush_mirror()
    return await _to_read(case, service)


@router.get("/{case_id}/timeline")
async def case_timeline(
    case_id: str,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> None:
    """Chronological reconstruction — requires normalized events (Sprint 2)."""
    raise not_implemented("timeline.case")


@router.get("/{case_id}/evidence-gaps")
async def case_evidence_gaps(
    case_id: str,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> None:
    """Collector outages, missing ranges, cleared logs (Sprint 7)."""
    raise not_implemented("gaps.detect")


@router.get("/{case_id}/contradictions")
async def case_contradictions(
    case_id: str,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> None:
    """Conflicting evidence across sources — never auto-resolved (Sprint 7)."""
    raise not_implemented("contradictions.detect")
