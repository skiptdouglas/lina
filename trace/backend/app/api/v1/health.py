"""Health, readiness and capability discovery."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep, get_state
from app.core.capabilities import CAPABILITIES

router = APIRouter(tags=["platform"])


class DependencyHealth(BaseModel):
    name: str
    status: str
    detail: str = ""
    required: bool = True


class ReadinessResponse(BaseModel):
    status: str
    dependencies: list[DependencyHealth]


class CapabilityRead(BaseModel):
    key: str
    title: str
    status: str
    sprint: int
    endpoints: list[str]
    detail: str


class CapabilitiesResponse(BaseModel):
    implemented: list[CapabilityRead]
    not_implemented: list[CapabilityRead]


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(request: Request, session: SessionDep, response: Response) -> ReadinessResponse:
    """Per-dependency readiness.

    Required dependencies (metadata DB, object store) decide the overall
    status. ClickHouse is reported but does not gate Sprint 1 functionality:
    the audit chain of record lives in the metadata store.
    """
    state = get_state(request)
    checks: list[DependencyHealth] = []

    try:
        await session.execute(text("SELECT 1"))
        checks.append(DependencyHealth(name="metadata_db", status="UP"))
    except Exception as exc:  # noqa: BLE001 - health probe reports, never raises
        checks.append(
            DependencyHealth(name="metadata_db", status="DOWN", detail=exc.__class__.__name__)
        )

    object_store_ok = await state.object_store.ping()
    checks.append(
        DependencyHealth(
            name="object_store",
            status="UP" if object_store_ok else "DOWN",
            detail=state.object_store.name,
        )
    )

    analytics_ok = await state.analytics.ping()
    checks.append(
        DependencyHealth(
            name="analytics",
            status="UP" if analytics_ok else "DEGRADED",
            detail=state.analytics.name,
            required=False,
        )
    )

    healthy = all(c.status == "UP" for c in checks if c.required)
    if not healthy:
        response.status_code = 503
    return ReadinessResponse(status="READY" if healthy else "NOT_READY", dependencies=checks)


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    """What TRACE can and cannot do yet (ADR-0004).

    The UI renders NOT IMPLEMENTED panels from this endpoint rather than
    showing empty charts that imply "no results".
    """
    implemented: list[CapabilityRead] = []
    pending: list[CapabilityRead] = []
    for capability in CAPABILITIES:
        item = CapabilityRead(
            key=capability.key,
            title=capability.title,
            status=capability.status,
            sprint=capability.sprint,
            endpoints=list(capability.endpoints),
            detail=capability.detail,
        )
        (implemented if capability.status == "IMPLEMENTED" else pending).append(item)
    return CapabilitiesResponse(implemented=implemented, not_implemented=pending)
