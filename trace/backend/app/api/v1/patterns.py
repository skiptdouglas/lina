"""Pattern Hunter, sequences, baselines and anomalies (Sprint 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import CASE_READ, DETECTION_RUN, Principal

router = APIRouter(tags=["patterns"])

SubjectKind = Literal["EVENT", "SEQUENCE", "PROCESS_TREE", "ENTITY", "CASE", "TIME_RANGE"]


class FindSimilarRequest(BaseModel):
    """Input for ``POST /api/v1/patterns/find-similar`` (brief §21)."""

    model_config = ConfigDict(extra="forbid")

    subject_kind: SubjectKind
    #: Identifier of the subject (event_id, entity_id, case_id ...) or an
    #: inline sequence/process-tree definition.
    subject_id: str | None = None
    subject: dict[str, Any] | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    limit: int = Field(default=20, ge=1, le=200)
    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)


class PatternMatch(BaseModel):
    case: str
    similarity: float
    subject_id: str | None = None
    #: What made it similar — a similarity score with no explanation is not analysis.
    explanation: str | None = None
    event_ids: list[str] = []


class FindSimilarResponse(BaseModel):
    matches: list[PatternMatch]


class SequenceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    sequence_id: str | None = None
    #: Inline definition, e.g. LOGIN → POWERSHELL → NETWORK_CONNECTION within 30m.
    steps: list[str] | None = None
    within_minutes: int = Field(default=30, ge=1, le=10080)


class SequenceMatch(BaseModel):
    sequence_id: str
    entity_id: str | None
    started_at: datetime
    completed_at: datetime
    event_ids: list[str] = Field(min_length=1)


class SequenceRunResponse(BaseModel):
    matches: list[SequenceMatch]


class AnomalyRead(BaseModel):
    """Every anomaly explains itself (brief §26)."""

    anomaly: str
    score: float
    reason: str
    method: str
    subject_type: str
    subject_id: str
    baseline_id: str | None = None
    event_ids: list[str] = []
    observed_at: datetime | None = None


class AnomalyList(BaseModel):
    items: list[AnomalyRead]


class BeaconRead(BaseModel):
    source: str
    destination: str
    port: int
    interval_seconds: float
    jitter: float
    packet_count: int
    byte_count: int
    periodicity: float
    confidence: float
    event_ids: list[str] = []


class BeaconList(BaseModel):
    items: list[BeaconRead]


@router.post("/patterns/find-similar", response_model=FindSimilarResponse)
async def find_similar(
    payload: FindSimilarRequest,
    principal: Annotated[Principal, Depends(require(DETECTION_RUN))],
) -> FindSimilarResponse:
    """Rank historical activity by similarity to a subject."""
    raise not_implemented("patterns.find_similar")


@router.post("/patterns/sequences/run", response_model=SequenceRunResponse)
async def run_sequences(
    payload: SequenceRunRequest,
    principal: Annotated[Principal, Depends(require(DETECTION_RUN))],
) -> SequenceRunResponse:
    raise not_implemented("patterns.sequences")


@router.get("/baselines/{subject_type}/{subject_id}")
async def get_baseline(
    subject_type: str,
    subject_id: str,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> None:
    raise not_implemented("baselines.behaviour")


@router.get("/anomalies", response_model=AnomalyList)
async def list_anomalies(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    case_id: Annotated[str | None, Query()] = None,
) -> AnomalyList:
    raise not_implemented("anomalies.statistical")


@router.get("/anomalies/beacons", response_model=BeaconList)
async def list_beacons(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    case_id: Annotated[str | None, Query()] = None,
) -> BeaconList:
    raise not_implemented("anomalies.beacons")


@router.get("/anomalies/exfiltration", response_model=AnomalyList)
async def list_exfiltration(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    case_id: Annotated[str | None, Query()] = None,
) -> AnomalyList:
    raise not_implemented("anomalies.exfiltration")
