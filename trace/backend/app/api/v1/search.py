"""Search endpoints (Sprint 2).

The contract is defined now so clients can be written against it; the handler
returns the 501 NOT_IMPLEMENTED contract rather than an empty result set,
which would be indistinguishable from "nothing matched".
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import SEARCH_QUERY, Principal

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=2000)
    case_id: str | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    user: str | None = None
    hostname: str | None = None
    ip: str | None = None
    domain: str | None = None
    process: str | None = None
    command_line: str | None = None
    hash: str | None = None
    event_type: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class SearchHitRead(BaseModel):
    event_id: str
    timestamp: datetime
    event_type: str
    score: float
    evidence_id: str
    raw_reference: str
    document: dict[str, Any]


class SearchResponse(BaseModel):
    hits: list[SearchHitRead]
    total: int
    took_ms: int


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    principal: Annotated[Principal, Depends(require(SEARCH_QUERY))],
) -> SearchResponse:
    raise not_implemented("search.query")
