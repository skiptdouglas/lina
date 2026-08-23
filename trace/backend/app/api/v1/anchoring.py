"""Evidence anchoring endpoints (docs/ANCHORING.md).

    Evidence -> SHA-256 -> manifest -> Merkle leaf -> root -> signed -> ledger
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response

from app.anchoring.schemas import (
    AnchorCreate,
    AnchorList,
    AnchorRead,
    AnchorVerifyResponse,
    BackendList,
    BackendStatus,
    BundleVerification,
    ConsistencyResponse,
    LeafList,
    LeafRead,
    LogStatus,
)
from app.anchoring.service import AnchoringService
from app.api.deps import AnchoringServiceDep, client_ip, require, user_agent
from app.core.security import ANCHOR_CREATE, ANCHOR_READ, Principal

router = APIRouter(tags=["anchoring"])


@router.get("/anchoring/log", response_model=LogStatus)
async def log_status(
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> LogStatus:
    """Size, current root, last anchor and the public key that signs tree heads."""
    return await service.log_status(principal)


@router.get("/anchoring/log/entries", response_model=LeafList)
async def log_entries(
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeafList:
    log = service.evidence_log(principal.tenant_id)
    leaves = await log.leaves(offset=offset, limit=limit)
    return LeafList(
        items=[LeafRead.model_validate(leaf) for leaf in leaves],
        total=await log.size(),
    )


@router.get("/anchoring/backends", response_model=BackendList)
async def list_backends(
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> BackendList:
    """Which ledgers this deployment can publish to, and how independent each is."""
    items: list[BackendStatus] = []
    for name, backend in sorted(service.backends.items()):
        usable, detail = await backend.available()
        items.append(
            BackendStatus(
                name=name,
                independence=backend.independence,
                available=usable,
                detail=detail,
                is_default=name == service.settings.anchor_backend,
            )
        )
    return BackendList(items=items)


@router.get("/anchoring/consistency", response_model=ConsistencyResponse)
async def consistency(
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
    first: Annotated[int, Query(ge=0)] = 0,
    second: Annotated[int, Query(ge=0)] = 0,
) -> ConsistencyResponse:
    """Prove the log only ever grew between two tree sizes.

    This is the check that catches a rewritten history: an operator who edited
    entry 3 after anchoring cannot produce a passing proof between the anchored
    root and the current one.
    """
    return await service.consistency(principal, first, second)


@router.post("/anchors", response_model=AnchorRead, status_code=201)
async def create_anchor(
    payload: AnchorCreate,
    request: Request,
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_CREATE))],
) -> AnchorRead:
    """Sign the current tree head and publish it to the ledger."""
    anchor = await service.create_anchor(
        principal,
        backend_name=payload.backend,
        include_audit_checkpoint=payload.include_audit_checkpoint,
        force=payload.force,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return AnchorRead.model_validate(anchor)


@router.get("/anchors", response_model=AnchorList)
async def list_anchors(
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AnchorList:
    anchors, total = await service.list_anchors(principal, limit=limit, offset=offset)
    return AnchorList(
        items=[AnchorRead.model_validate(a) for a in anchors],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/anchors/{anchor_id}", response_model=AnchorRead)
async def get_anchor(
    anchor_id: str,
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> AnchorRead:
    return AnchorRead.model_validate(await service.get_anchor(anchor_id, principal))


@router.post("/anchors/{anchor_id}/refresh", response_model=AnchorRead)
async def refresh_anchor(
    anchor_id: str,
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> AnchorRead:
    """Ask the backend whether a submitted anchor has confirmed yet."""
    return AnchorRead.model_validate(await service.refresh_anchor(anchor_id, principal))


@router.get("/anchors/{anchor_id}/verify", response_model=AnchorVerifyResponse)
async def verify_anchor(
    anchor_id: str,
    request: Request,
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> AnchorVerifyResponse:
    """Recompute the root from the log, re-check the signature, re-check the ledger."""
    return await service.verify_anchor(
        anchor_id,
        principal,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )


@router.get("/anchors/{anchor_id}/receipt")
async def download_receipt(
    anchor_id: str,
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> Response:
    """The backend's raw receipt — e.g. an ``.ots`` file for ``ots verify``."""
    import base64  # noqa: PLC0415

    from app.core.errors import NotFound  # noqa: PLC0415

    anchor = await service.get_anchor(anchor_id, principal)
    if not anchor.receipt_b64:
        raise NotFound(f"Anchor {anchor_id} has no stored receipt.")
    suffix = "ots" if anchor.backend == "opentimestamps" else "json"
    return Response(
        content=base64.b64decode(anchor.receipt_b64),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{anchor_id}.{suffix}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/evidence/{evidence_id}/proof")
async def evidence_proof(
    evidence_id: str,
    request: Request,
    service: AnchoringServiceDep,
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
) -> dict[str, Any]:
    """A self-contained proof bundle, verifiable offline with no access to TRACE.

    Contains no evidence bytes — only the manifest of immutable facts, the
    audit path, the signed tree head and the anchor receipt.
    """
    return await service.proof_bundle(
        evidence_id,
        principal,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )


@router.post("/anchoring/verify-bundle", response_model=BundleVerification)
async def verify_bundle(
    principal: Annotated[Principal, Depends(require(ANCHOR_READ))],
    bundle: Annotated[dict[str, Any], Body(description="A proof bundle produced by TRACE.")],
) -> BundleVerification:
    """Re-check a bundle.

    Convenience only. A bundle checked by the system that issued it proves less
    than one checked with ``scripts/verify_anchor.py`` on a machine TRACE does
    not control — which is the intended workflow.
    """
    return AnchoringService.verify_bundle(bundle)
