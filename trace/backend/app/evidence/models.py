"""Evidence metadata table (docs/DATA_MODEL.md §2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.timeutil import utcnow
from app.evidence.enums import AcquisitionMethod, ParseStatus, SourceType


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_tenant_case", "tenant_id", "case_id"),
        Index("ix_evidence_sha256", "sha256"),
    )

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(
        String(72), ForeignKey("cases.case_id"), nullable=False
    )

    source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SourceType.OTHER
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    collection_timestamp: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    original_timestamp: Mapped[datetime | None] = mapped_column(nullable=True)

    collector: Mapped[str] = mapped_column(
        String(128), nullable=False, default="manual-upload/1.0"
    )
    acquisition_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AcquisitionMethod.MANUAL_UPLOAD
    )

    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="application/octet-stream"
    )
    mime_type_source: Mapped[str] = mapped_column(String(16), nullable=False, default="declared")

    storage_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    retention_policy: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default-365d"
    )
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ParseStatus.PENDING
    )
    parse_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_verification_result: Mapped[str | None] = mapped_column(String(16), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
