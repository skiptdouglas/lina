"""Reporting and threat intelligence (Sprint 7)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import CASE_READ, REPORT_GENERATE, Principal
from app.reports.sections import REPORT_SECTIONS

router = APIRouter(tags=["reports"])


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    format: str = Field(default="pdf", pattern="^(pdf|html|markdown|json)$")
    sections: list[str] | None = None
    include_appendices: bool = True


class ReportResponse(BaseModel):
    report_id: str
    case_id: str
    format: str
    sections: list[str]
    storage_key: str
    sha256: str


@router.get("/reports/sections")
async def report_sections(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> dict[str, list[str]]:
    """The section list a generated report will contain (brief §42).

    Implemented because it is static metadata, not analysis.
    """
    return {"sections": list(REPORT_SECTIONS)}


@router.post("/reports/generate", response_model=ReportResponse)
async def generate_report(
    payload: ReportRequest,
    principal: Annotated[Principal, Depends(require(REPORT_GENERATE))],
) -> ReportResponse:
    raise not_implemented("reports.generate")


@router.get("/threatintel/enrich")
async def enrich(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    indicator: Annotated[str, Query(min_length=1, max_length=2048)] = "",
) -> None:
    """Enrich an indicator from MISP/OpenCTI/TAXII — enrichment, never replacement."""
    raise not_implemented("threatintel.enrich")
