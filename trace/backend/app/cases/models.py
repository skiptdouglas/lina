"""Case table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.cases.enums import CaseStatus, Severity
from app.core.db import Base
from app.core.timeutil import utcnow


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (Index("ix_cases_tenant_status", "tenant_id", "status"),)

    case_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CaseStatus.OPEN)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.MEDIUM)
    investigator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
