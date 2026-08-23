"""Parsing control."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel

from app.api.deps import ParseServiceDep, client_ip, require, user_agent
from app.core.security import EVIDENCE_CREATE, Principal
from app.evidence.enums import ParseStatus
from app.normalization.parsers import registry

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


class ParseResponse(BaseModel):
    """What a parse actually did — including what it could not do."""

    evidence_id: str
    parse_status: ParseStatus
    parser_id: str | None
    events_produced: int
    records_read: int
    records_skipped: int
    unrecognised: int
    unrecognised_types: dict[str, int] = {}
    errors: list[str] = []
    truncated: bool = False
    truncation_reason: str = ""
    detail: str


class ParserInfo(BaseModel):
    parser_id: str
    handles: list[str]
    supported_records: list[str]
    description: str


class ParserList(BaseModel):
    items: list[ParserInfo]


@router.get("/parsers", response_model=ParserList)
async def list_parsers(
    principal: Annotated[Principal, Depends(require(EVIDENCE_CREATE))],
) -> ParserList:
    """Which formats TRACE can normalize, and which record types within them.

    Coverage is a forensic question, not a feature list: an analyst needs to
    know that Sysmon event 15 is not mapped before concluding it did not occur.
    """
    return ParserList(
        items=[
            ParserInfo(
                parser_id=parser.parser_id,
                handles=[str(handled) for handled in parser.handles],
                supported_records=list(parser.supported_records),
                description=parser.description,
            )
            for parser in registry.all()
        ]
    )


@router.post("/parse/{evidence_id}", response_model=ParseResponse)
async def parse_evidence(
    evidence_id: str,
    request: Request,
    parser: ParseServiceDep,
    principal: Annotated[Principal, Depends(require(EVIDENCE_CREATE))],
    force: Annotated[bool, Body(embed=True)] = False,
) -> ParseResponse:
    """Parse stored evidence into normalized events.

    Reads a fresh copy from object storage — never the upload stream (ADR-0005).
    Re-parsing replaces this artifact's events rather than duplicating them, so
    a fixed parser or a corrected clock offset can be applied safely.
    """
    report = await parser.parse_evidence(
        evidence_id,
        principal,
        force=force,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return ParseResponse(**asdict(report))
