"""Request dependencies: state, sessions, principals, services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.anchoring.service import AnchoringService
from app.audit.service import AuditService
from app.cases.service import CaseService
from app.core.config import Settings
from app.core.security import Principal
from app.core.state import AppState
from app.evidence.service import EvidenceService
from app.evidence.storage import ObjectStore
from app.ingestion.service import IngestionService

bearer_scheme = HTTPBearer(auto_error=False, description="TRACE API token")


def get_state(request: Request) -> AppState:
    return request.app.state.trace


def get_settings(request: Request) -> Settings:
    return get_state(request).settings


def get_object_store(request: Request) -> ObjectStore:
    return get_state(request).object_store


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    state = get_state(request)
    async with state.database.session_factory() as session:
        yield session


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> Principal:
    state = get_state(request)
    token = credentials.credentials if credentials else None
    return state.authenticator.authenticate(token)


def require(*permissions: str):
    """Route dependency enforcing the permission matrix (docs/SECURITY.md §3)."""

    def _dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        principal.require(*permissions)
        return principal

    return _dependency


def client_ip(request: Request) -> str | None:
    """Best-effort client address.

    ``X-Forwarded-For`` is trusted only because the deployment terminates TLS at
    a reverse proxy it controls; a direct-exposure deployment must strip it.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("User-Agent")


def get_audit_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuditService:
    state = get_state(request)
    return AuditService(
        session,
        mirror=state.audit_mirror,
        fail_closed=state.settings.audit_fail_closed,
    )


def get_case_service(session: Annotated[AsyncSession, Depends(get_session)]) -> CaseService:
    return CaseService(session)


def get_evidence_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> EvidenceService:
    state = get_state(request)
    return EvidenceService(
        session, store=state.object_store, audit=audit, settings=state.settings
    )


def get_ingestion_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    anchoring: Annotated[AnchoringService, Depends(get_anchoring_service)],
) -> IngestionService:
    state = get_state(request)
    return IngestionService(
        session,
        store=state.object_store,
        audit=audit,
        queue=state.queue,
        settings=state.settings,
        anchoring=anchoring if state.signer is not None else None,
    )


def get_anchoring_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> AnchoringService:
    state = get_state(request)
    return AnchoringService(
        session,
        settings=state.settings,
        signer=state.signer,
        backends=state.anchor_backends,
        audit=audit,
    )


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
AuditDep = Annotated[AuditService, Depends(get_audit_service)]
CaseServiceDep = Annotated[CaseService, Depends(get_case_service)]
EvidenceServiceDep = Annotated[EvidenceService, Depends(get_evidence_service)]
IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
AnchoringServiceDep = Annotated[AnchoringService, Depends(get_anchoring_service)]
