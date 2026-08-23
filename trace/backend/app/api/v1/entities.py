"""Entities, graph and identity reveal (Sprints 3 and 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require
from app.core.capabilities import not_implemented
from app.core.security import CASE_READ, IDENTITY_REVEAL, Principal

router = APIRouter(tags=["entities"])


class EntityRead(BaseModel):
    entity_id: str
    entity_type: str
    canonical_name: str
    aliases: list[str]
    first_seen: datetime | None
    last_seen: datetime | None
    event_count: int


class EntityList(BaseModel):
    items: list[EntityRead]
    total: int


class GraphNode(BaseModel):
    entity_id: str
    entity_type: str
    label: str
    attributes: dict[str, Any] = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str
    #: Never empty — an edge without supporting events is an assertion, not evidence.
    event_ids: list[str] = Field(min_length=1)
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    reason: str = Field(min_length=10, max_length=2000)


class RevealResponse(BaseModel):
    entity_id: str
    revealed_identifier: str
    revealed_at: datetime
    audit_id: str


@router.get("/entities", response_model=EntityList)
async def list_entities(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    case_id: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
) -> EntityList:
    raise not_implemented("entities.registry")


@router.get("/entities/{entity_id}", response_model=EntityRead)
async def get_entity(
    entity_id: str,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
) -> EntityRead:
    raise not_implemented("entities.registry")


@router.post("/entities/{entity_id}/reveal", response_model=RevealResponse)
async def reveal_entity(
    entity_id: str,
    payload: RevealRequest,
    principal: Annotated[Principal, Depends(require(IDENTITY_REVEAL))],
) -> RevealResponse:
    """De-pseudonymise an entity. Authorised, reasoned and audited (brief §31)."""
    raise not_implemented("privacy.reveal")


@router.get("/graph/neighbourhood", response_model=GraphResponse)
async def graph_neighbourhood(
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    entity_id: Annotated[str, Query()] = "",
    depth: Annotated[int, Query(ge=1, le=4)] = 2,
) -> GraphResponse:
    raise not_implemented("graph.neighbourhood")
