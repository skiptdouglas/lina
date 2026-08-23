"""Parsing control (Sprint 2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import EVIDENCE_CREATE, Principal

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


class ParseResponse(BaseModel):
    evidence_id: str
    parse_status: str
    events_produced: int
    detail: str


@router.post("/parse/{evidence_id}", response_model=ParseResponse)
async def parse_evidence(
    evidence_id: str,
    principal: Annotated[Principal, Depends(require(EVIDENCE_CREATE))],
) -> ParseResponse:
    """Parse stored evidence into normalized events.

    Parsers read a fresh copy from object storage — never the upload stream.
    """
    raise not_implemented("ingestion.parse")
