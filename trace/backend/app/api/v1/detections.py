"""Sigma, YARA, MITRE and hunting endpoints (Sprint 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import CASE_READ, DETECTION_RUN, Principal

router = APIRouter(tags=["detections"])


class MitreMapping(BaseModel):
    tactic: str
    technique: str
    subtechnique: str | None = None
    technique_name: str | None = None


class DetectionHit(BaseModel):
    detection_id: str
    rule_id: str
    rule_type: str
    title: str
    severity: str
    mitre: MitreMapping | None = None
    #: Provenance is mandatory — see docs/ARCHITECTURE.md §7.
    event_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class SigmaRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    rule_ids: list[str] | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None


class SigmaRunResponse(BaseModel):
    rules_evaluated: int
    hits: list[DetectionHit]
    took_ms: int


class YaraScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[str] = Field(min_length=1)
    rule_ids: list[str] | None = None


class YaraScanResponse(BaseModel):
    scanned: int
    hits: list[DetectionHit]


class RareEventRow(BaseModel):
    value: str
    dimension: str
    first_seen: datetime
    last_seen: datetime
    event_count: int
    host_count: int
    user_count: int


class RareEventResponse(BaseModel):
    items: list[RareEventRow]


@router.post("/detections/sigma/run", response_model=SigmaRunResponse)
async def run_sigma(
    payload: SigmaRunRequest,
    principal: Annotated[Principal, Depends(require(DETECTION_RUN))],
) -> SigmaRunResponse:
    """Run Sigma rules against historical data (retro-hunt)."""
    raise not_implemented("detections.sigma")


@router.post("/detections/yara/scan", response_model=YaraScanResponse)
async def run_yara(
    payload: YaraScanRequest,
    principal: Annotated[Principal, Depends(require(DETECTION_RUN))],
) -> YaraScanResponse:
    """Scan stored evidence with YARA/YARA-X in an isolated worker."""
    raise not_implemented("detections.yara")


@router.get("/detections/mitre/coverage")
async def mitre_coverage(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    case_id: Annotated[str | None, Query()] = None,
) -> None:
    raise not_implemented("detections.mitre")


@router.get("/hunt/rare", response_model=RareEventResponse)
async def hunt_rare(
    principal: Annotated[Principal, Depends(require(DETECTION_RUN))],
    case_id: Annotated[str | None, Query()] = None,
    dimension: Annotated[str, Query()] = "process.name",
) -> RareEventResponse:
    raise not_implemented("hunt.rare")


@router.get("/hunt/first-seen", response_model=RareEventResponse)
async def hunt_first_seen(
    principal: Annotated[Principal, Depends(require(DETECTION_RUN))],
    case_id: Annotated[str | None, Query()] = None,
    dimension: Annotated[str, Query()] = "process.hash.sha256",
) -> RareEventResponse:
    raise not_implemented("hunt.first_seen")
