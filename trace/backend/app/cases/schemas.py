"""Case request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.cases.enums import CaseStatus, Severity
from app.core.ids import is_valid_case_id


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20000)
    severity: Severity = Severity.MEDIUM
    status: CaseStatus = CaseStatus.OPEN
    investigator: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=32)
    #: Optional explicit identifier, e.g. ``CASE-DEMO-001``. Allocated when omitted.
    case_id: str | None = None

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().upper()
        if not is_valid_case_id(candidate):
            raise ValueError("case_id must look like CASE-0042 or CASE-DEMO-001")
        return candidate


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20000)
    severity: Severity | None = None
    status: CaseStatus | None = None
    investigator: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = Field(default=None, max_length=32)


class CaseCounts(BaseModel):
    """Relations are returned as counts + sub-resource links, never inlined."""

    evidence: int = 0
    entities: int | None = None
    findings: int | None = None


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    tenant_id: str
    title: str
    description: str | None
    status: CaseStatus
    severity: Severity
    investigator: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    counts: CaseCounts = CaseCounts()


class CaseList(BaseModel):
    items: list[CaseRead]
    total: int
    limit: int
    offset: int
