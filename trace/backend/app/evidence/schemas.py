"""Evidence request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.enums import AcquisitionMethod, ParseStatus, SourceType, VerificationResult
from app.evidence.integrity import HASH_ALGORITHM


class EvidenceIngestMetadata(BaseModel):
    """Non-file parts of ``POST /api/v1/evidence``."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=3, max_length=72)
    source: str = Field(min_length=1, max_length=255)
    source_type: SourceType = SourceType.OTHER
    collector: str = Field(default="manual-upload/1.0", max_length=128)
    acquisition_method: AcquisitionMethod = AcquisitionMethod.MANUAL_UPLOAD
    original_path: str | None = Field(default=None, max_length=4096)
    original_timestamp: datetime | None = None
    collection_timestamp: datetime | None = None
    retention_policy: str = Field(default="default-365d", max_length=64)
    legal_hold: bool = False
    notes: str | None = Field(default=None, max_length=20000)


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: str
    case_id: str
    tenant_id: str
    source: str
    source_type: SourceType
    original_filename: str
    original_path: str | None
    collection_timestamp: datetime
    original_timestamp: datetime | None
    collector: str
    acquisition_method: AcquisitionMethod
    size: int
    sha256: str
    mime_type: str
    storage_bucket: str
    storage_key: str
    retention_policy: str
    legal_hold: bool
    parse_status: ParseStatus
    parse_detail: str | None
    last_verified_at: datetime | None
    last_verification_result: VerificationResult | None
    notes: str | None
    created_at: datetime


class EvidenceList(BaseModel):
    items: list[EvidenceRead]
    total: int
    limit: int
    offset: int


class VerificationResponse(BaseModel):
    """Response of ``GET /api/v1/evidence/{id}/verify`` (brief §8)."""

    verified: bool
    expected_hash: str
    actual_hash: str | None
    evidence_id: str
    algorithm: str = HASH_ALGORITHM
    size_expected: int
    size_actual: int | None = None
    result: VerificationResult
    verified_at: datetime
    detail: str
