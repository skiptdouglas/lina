"""Evidence endpoints (brief §7, §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import (
    EvidenceServiceDep,
    IngestionServiceDep,
    SettingsDep,
    client_ip,
    require,
    user_agent,
)
from app.core.errors import PayloadTooLarge, ValidationFailure
from app.core.security import (
    EVIDENCE_CREATE,
    EVIDENCE_DOWNLOAD,
    EVIDENCE_READ,
    EVIDENCE_VERIFY,
    Principal,
)
from app.evidence.enums import AcquisitionMethod, SourceType
from app.evidence.schemas import (
    EvidenceIngestMetadata,
    EvidenceList,
    EvidenceRead,
    VerificationResponse,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])

UPLOAD_CHUNK = 1024 * 1024


async def _iter_upload(upload: UploadFile, chunk_size: int = UPLOAD_CHUNK):
    """Yield the upload in chunks.

    Starlette has already spooled the multipart body, so this is a copy rather
    than a true end-to-end stream; hashing and the byte cap still run over the
    stream. True streaming ingest (chunked/resumable upload) is a Sprint 2 item.
    """
    while chunk := await upload.read(chunk_size):
        yield chunk


@router.post("", response_model=EvidenceRead, status_code=201)
async def ingest_evidence(
    request: Request,
    ingestion: IngestionServiceDep,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require(EVIDENCE_CREATE))],
    file: Annotated[UploadFile, File(description="The original artifact.")],
    case_id: Annotated[str, Form()],
    source: Annotated[str, Form()],
    source_type: Annotated[SourceType, Form()] = SourceType.OTHER,
    collector: Annotated[str, Form()] = "manual-upload/1.0",
    acquisition_method: Annotated[AcquisitionMethod, Form()] = AcquisitionMethod.MANUAL_UPLOAD,
    original_path: Annotated[str | None, Form()] = None,
    original_timestamp: Annotated[datetime | None, Form()] = None,
    collection_timestamp: Annotated[datetime | None, Form()] = None,
    retention_policy: Annotated[str, Form()] = "default-365d",
    legal_hold: Annotated[bool, Form()] = False,
    notes: Annotated[str | None, Form()] = None,
) -> EvidenceRead:
    """Upload an artifact, hash it, store it, prove it was stored, then queue parsing.

    The raw object is written before anything is parsed, and the stored copy is
    re-read and re-hashed before the metadata row is committed (ADR-0005).
    """
    declared_length = request.headers.get("Content-Length")
    if declared_length and declared_length.isdigit():
        # Fast rejection only. The authoritative check counts received bytes;
        # a hard limit also belongs in the reverse proxy.
        if int(declared_length) > settings.evidence_max_upload_bytes:
            raise PayloadTooLarge(
                f"Upload exceeds the configured maximum of "
                f"{settings.evidence_max_upload_bytes} bytes."
            )

    metadata = EvidenceIngestMetadata(
        case_id=case_id.strip().upper(),
        source=source,
        source_type=source_type,
        collector=collector,
        acquisition_method=acquisition_method,
        original_path=original_path or None,
        original_timestamp=original_timestamp,
        collection_timestamp=collection_timestamp,
        retention_policy=retention_policy,
        legal_hold=legal_hold,
        notes=notes or None,
    )
    evidence = await ingestion.ingest(
        stream=_iter_upload(file),
        filename=file.filename,
        declared_content_type=file.content_type,
        metadata=metadata,
        principal=principal,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return EvidenceRead.model_validate(evidence)


@router.get("", response_model=EvidenceList)
async def list_evidence(
    service: EvidenceServiceDep,
    principal: Annotated[Principal, Depends(require(EVIDENCE_READ))],
    case_id: Annotated[str | None, Query(max_length=72)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceList:
    rows, total = await service.list(principal, case_id=case_id, limit=limit, offset=offset)
    return EvidenceList(
        items=[EvidenceRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{evidence_id}", response_model=EvidenceRead)
async def get_evidence(
    evidence_id: str,
    service: EvidenceServiceDep,
    principal: Annotated[Principal, Depends(require(EVIDENCE_READ))],
) -> EvidenceRead:
    evidence = await service.get(evidence_id, principal)
    return EvidenceRead.model_validate(evidence)


@router.get("/{evidence_id}/verify", response_model=VerificationResponse)
async def verify_evidence(
    evidence_id: str,
    request: Request,
    service: EvidenceServiceDep,
    principal: Annotated[Principal, Depends(require(EVIDENCE_VERIFY))],
) -> VerificationResponse:
    """Recalculate the digest of the stored object and compare it with the record.

    Always audited — a failed verification is the most important one to record.
    """
    return await service.verify(
        evidence_id,
        principal,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )


@router.get("/{evidence_id}/download")
async def download_evidence(
    evidence_id: str,
    request: Request,
    service: EvidenceServiceDep,
    principal: Annotated[Principal, Depends(require(EVIDENCE_DOWNLOAD))],
    reason: Annotated[str, Query(min_length=3, max_length=2000)] = "",
) -> StreamingResponse:
    """Return the original bytes. Requires a written justification (audited)."""
    if not reason.strip():
        raise ValidationFailure("A reason is required to download original evidence.")

    evidence, stream = await service.open_download(
        evidence_id,
        principal,
        reason=reason.strip(),
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    # Never served with a browser-renderable content type (docs/SECURITY.md §5).
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{evidence.original_filename}"',
            "Content-Length": str(evidence.size),
            "X-TRACE-Evidence-Id": evidence.evidence_id,
            "X-TRACE-SHA256": evidence.sha256,
            "X-Content-Type-Options": "nosniff",
        },
    )
