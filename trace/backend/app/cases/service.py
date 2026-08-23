"""Case management.

Case identifiers are allocated from a counter table so they are human
readable (``CASE-0042``) and stable, while explicit identifiers such as
``CASE-DEMO-001`` remain possible.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.enums import CaseStatus
from app.cases.models import Case
from app.cases.schemas import CaseCounts, CaseCreate, CaseUpdate
from app.core.errors import Conflict, NotFound
from app.core.ids import format_case_id
from app.core.models import Counter
from app.core.security import Principal
from app.core.timeutil import utcnow
from app.evidence.models import Evidence

CASE_COUNTER = "case_number"

_allocation_lock = asyncio.Lock()


class CaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _next_case_id(self, tenant_id: str) -> str:
        """Allocate the next ``CASE-NNNN`` for a tenant.

        Serialized in-process; a multi-replica deployment should move this to a
        database sequence (see docs/ROADMAP.md backlog).
        """
        name = f"{CASE_COUNTER}:{tenant_id}"
        async with _allocation_lock:
            counter = await self.session.get(Counter, name)
            if counter is None:
                counter = Counter(name=name, value=0)
                self.session.add(counter)
            for _ in range(1000):
                counter.value += 1
                candidate = format_case_id(counter.value)
                exists = await self.session.get(Case, candidate)
                if exists is None:
                    await self.session.flush()
                    return candidate
            raise Conflict("Unable to allocate a case identifier.")  # pragma: no cover

    async def create(self, payload: CaseCreate, principal: Principal) -> Case:
        case_id = payload.case_id
        if case_id is not None:
            existing = await self.session.get(Case, case_id)
            if existing is not None:
                raise Conflict(f"Case {case_id} already exists.")
        else:
            case_id = await self._next_case_id(principal.tenant_id)

        now = utcnow()
        case = Case(
            case_id=case_id,
            tenant_id=principal.tenant_id,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            severity=payload.severity,
            investigator=payload.investigator or principal.subject,
            tags=list(payload.tags),
            created_at=now,
            updated_at=now,
        )
        self.session.add(case)
        await self.session.flush()
        return case

    async def get(self, case_id: str, principal: Principal) -> Case:
        """Cross-tenant reads return 404 rather than 403 (docs/SECURITY.md §4)."""
        case = await self.session.get(Case, case_id)
        if case is None or case.tenant_id != principal.tenant_id:
            raise NotFound(f"Case {case_id} not found.")
        return case

    async def list(
        self,
        principal: Principal,
        *,
        status: CaseStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Case], int]:
        stmt = select(Case).where(Case.tenant_id == principal.tenant_id)
        count_stmt = (
            select(func.count())
            .select_from(Case)
            .where(Case.tenant_id == principal.tenant_id)
        )
        if status is not None:
            stmt = stmt.where(Case.status == status)
            count_stmt = count_stmt.where(Case.status == status)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(Case.title.ilike(pattern))
            count_stmt = count_stmt.where(Case.title.ilike(pattern))

        stmt = stmt.order_by(Case.created_at.desc()).limit(limit).offset(offset)
        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), total

    async def update(self, case_id: str, payload: CaseUpdate, principal: Principal) -> Case:
        case = await self.get(case_id, principal)
        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(case, field, value)
        closed = data.get("status") in (CaseStatus.CLOSED, CaseStatus.ARCHIVED)
        if closed and case.closed_at is None:
            case.closed_at = utcnow()
        reopened = "status" in data and data["status"] not in (
            CaseStatus.CLOSED,
            CaseStatus.ARCHIVED,
        )
        if reopened:
            case.closed_at = None
        case.updated_at = utcnow()
        await self.session.flush()
        return case

    async def counts(self, case: Case) -> CaseCounts:
        evidence_total = (
            await self.session.execute(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.case_id == case.case_id, Evidence.tenant_id == case.tenant_id)
            )
        ).scalar_one()
        # entities/findings arrive in Sprints 3/4; ``None`` means "not yet
        # computed", which the UI renders as NOT IMPLEMENTED rather than 0.
        return CaseCounts(evidence=evidence_total, entities=None, findings=None)
