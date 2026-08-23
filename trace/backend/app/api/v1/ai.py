"""AI investigator endpoints (Sprint 6).

No LLM is wired up yet. TRACE returns 501 rather than an unsourced answer:
an AI response that cannot cite evidence is not analysis, it is decoration.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import InvestigationResponse
from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import AI_QUERY, Principal

router = APIRouter(prefix="/ai", tags=["ai"])


class InvestigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    question: str = Field(min_length=3, max_length=4000)
    #: Optional scope hints; the retriever decides what context to fetch.
    entity_ids: list[str] | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


@router.post("/investigate", response_model=InvestigationResponse)
async def investigate(
    payload: InvestigateRequest,
    principal: Annotated[Principal, Depends(require(AI_QUERY))],
) -> InvestigationResponse:
    """Answer a question about a case using retrieved, evidence-linked context."""
    raise not_implemented("ai.investigate")
