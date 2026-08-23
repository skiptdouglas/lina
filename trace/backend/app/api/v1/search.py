"""Search and timeline endpoints.

Both are the same query against the same store; they differ in ordering and in
what an analyst is asking. Search answers "where does this appear?" (newest
first). A timeline answers "what happened?" (oldest first, in sequence).

Every response reports which backend answered and what that backend can
actually do, so "no results" is never ambiguous between *nothing matched* and
*this backend cannot express that query*.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import (
    AuditDep,
    CaseServiceDep,
    EventStoreDep,
    SearchBackendDep,
    SessionDep,
    client_ip,
    require,
    user_agent,
)
from app.audit.actions import AuditAction
from app.core.security import CASE_READ, SEARCH_QUERY, Principal
from app.events.store import EventQuery
from app.normalization.schema import NormalizedEvent

router = APIRouter(tags=["search"])


class BackendCapabilities(BaseModel):
    """What the answering backend can express."""

    name: str
    full_text: bool
    fuzzy: bool
    wildcard: bool
    regex: bool
    aggregation: bool
    notes: str


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

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
    category: str | None = None
    min_severity: int | None = Field(default=None, ge=0, le=10)
    evidence_id: str | None = None
    entity: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    ascending: bool = False

    def to_event_query(self, tenant_id: str) -> EventQuery:
        return EventQuery(
            tenant_id=tenant_id,
            case_id=self.case_id,
            text=self.query,
            time_from=self.from_,
            time_to=self.to,
            event_types=(self.event_type,) if self.event_type else (),
            categories=(self.category,) if self.category else (),
            min_severity=self.min_severity,
            user=self.user,
            hostname=self.hostname,
            ip=self.ip,
            domain=self.domain,
            process=self.process,
            command_line=self.command_line,
            file_hash=self.hash,
            evidence_id=self.evidence_id,
            entity=self.entity,
            limit=self.limit,
            offset=self.offset,
            ascending=self.ascending,
        )


class SearchResponse(BaseModel):
    events: list[NormalizedEvent]
    total: int
    limit: int
    offset: int
    took_ms: int
    backend: BackendCapabilities


class TimelineEntry(BaseModel):
    """One event on a timeline, with the timestamps kept separate.

    ``timestamp`` is what the event is ordered by; ``original_timestamp`` is
    what the source claimed. They differ only when a clock offset was applied,
    and the correction is reported alongside so the ordering is auditable.
    """

    event: NormalizedEvent
    #: True when a clock correction moved this event relative to the source.
    clock_corrected: bool
    #: How to reach the original bytes: evidence id + record locator.
    provenance: dict[str, Any]


class TimelineResponse(BaseModel):
    case_id: str
    entries: list[TimelineEntry]
    total: int
    limit: int
    offset: int
    took_ms: int
    backend: BackendCapabilities
    #: Present when any event in the window carries a clock correction.
    clock_corrections_applied: bool


def _capabilities(backend) -> BackendCapabilities:  # noqa: ANN001
    caps = backend.capabilities()
    return BackendCapabilities(
        name=caps.name,
        full_text=caps.full_text,
        fuzzy=caps.fuzzy,
        wildcard=caps.wildcard,
        regex=caps.regex,
        aggregation=caps.aggregation,
        notes=caps.notes,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    request: Request,
    backend: SearchBackendDep,
    audit: AuditDep,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require(SEARCH_QUERY))],
) -> SearchResponse:
    """Search normalized events.

    Searches are audited: who looked for what is part of the investigation
    record, and investigation replay (brief §41) is built from it.
    """
    page = await backend.search(payload.to_event_query(principal.tenant_id))

    await audit.record(
        action=AuditAction.SEARCH,
        principal=principal,
        case_id=payload.case_id,
        source_ip=client_ip(request),
        user_agent=user_agent(request),
        details={
            "query": payload.model_dump(exclude_none=True, exclude={"limit", "offset"}),
            "results": page.total,
            "backend": page.backend,
        },
    )
    await session.commit()
    await audit.flush_mirror()

    return SearchResponse(
        events=page.events,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        took_ms=page.took_ms,
        backend=_capabilities(backend),
    )


@router.get("/cases/{case_id}/timeline", response_model=TimelineResponse)
async def case_timeline(
    case_id: str,
    cases: CaseServiceDep,
    events: EventStoreDep,
    principal: Annotated[Principal, Depends(require(CASE_READ))],
    entity: Annotated[str | None, Query(max_length=255)] = None,
    event_type: Annotated[str | None, Query(max_length=64)] = None,
    category: Annotated[str | None, Query(max_length=32)] = None,
    min_severity: Annotated[int | None, Query(ge=0, le=10)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TimelineResponse:
    """Chronological reconstruction for a case.

    Ordered by the clock-corrected timestamp, with the original preserved on
    every entry — TRACE never overwrites what the source claimed (brief §17).
    """
    case = await cases.get(case_id, principal)

    page = await events.search(
        EventQuery(
            tenant_id=principal.tenant_id,
            case_id=case.case_id,
            entity=entity,
            event_types=(event_type,) if event_type else (),
            categories=(category,) if category else (),
            min_severity=min_severity,
            time_from=from_,
            time_to=to,
            limit=limit,
            offset=offset,
            ascending=True,
        )
    )

    entries = [
        TimelineEntry(
            event=event,
            clock_corrected=event.timestamp != event.original_timestamp,
            provenance={
                "evidence_id": event.evidence_id,
                "raw_reference": event.raw_reference,
                "record_url": (
                    f"/api/v1/evidence/{event.evidence_id}/record"
                    f"?reference={event.raw_reference}"
                ),
            },
        )
        for event in page.events
    ]

    return TimelineResponse(
        case_id=case.case_id,
        entries=entries,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        took_ms=page.took_ms,
        backend=_capabilities(events),
        clock_corrections_applied=any(entry.clock_corrected for entry in entries),
    )


@router.get("/events/{event_id}", response_model=NormalizedEvent)
async def get_event(
    event_id: str,
    events: EventStoreDep,
    principal: Annotated[Principal, Depends(require(SEARCH_QUERY))],
) -> NormalizedEvent:
    from app.core.errors import NotFound  # noqa: PLC0415

    event = await events.get_event(principal.tenant_id, event_id)
    if event is None:
        raise NotFound(f"Event {event_id} not found.")
    return event
