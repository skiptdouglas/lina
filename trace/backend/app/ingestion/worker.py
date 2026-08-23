"""Background parse worker.

Ingest enqueues; this drains. The split matters: an upload must return as soon
as the evidence is safely stored and verified (Sprint 1's guarantee), and
parsing a 40 GB image cannot be on that path.

Failure isolation is the design point. One artifact that cannot be parsed —
a truncated log, an unknown format, a parser bug — must not stall the queue or
stop the ones behind it. Every job is caught, recorded on the evidence row, and
the worker moves on.
"""

from __future__ import annotations

import asyncio
import logging

from app.audit.service import AuditService
from app.core.config import Settings
from app.core.security import Principal, Role
from app.core.state import AppState
from app.ingestion.queue import ParseJob
from app.normalization.service import ParseService

logger = logging.getLogger(__name__)


def system_principal(tenant_id: str) -> Principal:
    """The identity background parsing acts under.

    A real principal, not a bypass: its actions are audited like anyone's, and
    it holds SERVICE rights only.
    """
    return Principal(
        subject="system.parser",
        tenant_id=tenant_id,
        roles=frozenset({Role.SERVICE}),
        display_name="Automatic parsing",
        auth_method="system",
    )


class ParseWorker:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.settings: Settings = state.settings

    async def run_once(self, limit: int = 25) -> int:
        """Drain up to ``limit`` queued jobs. Returns how many were processed."""
        queue = self.state.queue
        processed = 0
        for _ in range(limit):
            job = await queue.dequeue()
            if job is None:
                break
            await self._process(job)
            processed += 1
        return processed

    async def _process(self, job: ParseJob) -> None:
        try:
            async with self.state.database.session_factory() as session:
                audit = AuditService(
                    session,
                    mirror=self.state.audit_mirror,
                    fail_closed=self.settings.audit_fail_closed,
                )
                service = ParseService(
                    session,
                    store=self.state.object_store,
                    events=self.state.events,
                    audit=audit,
                    settings=self.settings,
                    search=self.state.search,
                )
                report = await service.parse_evidence(
                    job.evidence_id, system_principal(job.tenant_id), force=True
                )
            logger.info(
                "Parsed %s with %s: %d event(s) from %d record(s) [%s]",
                job.evidence_id,
                report.parser_id,
                report.events_produced,
                report.records_read,
                report.parse_status,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad artifact must not stall the queue
            logger.error("Parsing %s failed: %s", job.evidence_id, exc)
            await self._mark_failed(job, exc)

    async def _mark_failed(self, job: ParseJob, exc: Exception) -> None:
        """Record the failure on the evidence row so it is visible in the UI."""
        from app.evidence.enums import ParseStatus  # noqa: PLC0415
        from app.evidence.models import Evidence  # noqa: PLC0415

        try:
            async with self.state.database.session_factory() as session:
                evidence = await session.get(Evidence, job.evidence_id)
                if evidence is not None:
                    evidence.parse_status = ParseStatus.FAILED
                    evidence.parse_detail = (
                        f"Parsing failed: {exc.__class__.__name__}: {exc}. The raw evidence "
                        f"is untouched and can be re-parsed once the cause is fixed."
                    )
                    await session.commit()
        except Exception as inner:  # noqa: BLE001 - best effort
            logger.error("Could not record the parse failure for %s: %s", job.evidence_id, inner)

    async def run_forever(self, interval_seconds: float = 2.0) -> None:
        while True:
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must outlive any single tick
                logger.error("Parse worker tick failed: %s", exc)
                processed = 0
            # Back off when idle; drain eagerly when there is work.
            await asyncio.sleep(0 if processed else interval_seconds)
