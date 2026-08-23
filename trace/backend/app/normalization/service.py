"""Parsing: raw artifact in object storage -> normalized events in the store.

Reads a **fresh copy** from object storage every time. The upload stream is
never the input, so parsing can be re-run as often as needed and can never
consume the only copy of an artifact (ADR-0005).

Re-parsing is idempotent: events derived from an artifact are removed before
the new ones are written, so a fixed parser or a corrected clock offset can be
applied without duplicating a case's timeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import AuditService
from app.core.config import Settings
from app.core.errors import Conflict, NotFound
from app.core.security import Principal
from app.events.store import EventStore
from app.evidence.enums import ParseStatus, SourceType
from app.evidence.models import Evidence
from app.evidence.service import EvidenceService
from app.evidence.storage import ObjectNotFound, ObjectStore
from app.normalization.jsonl import ReadLimits
from app.normalization.parsers import ParseContext, ParserRegistry
from app.normalization.parsers import registry as default_registry
from app.search.backend import SearchBackend
from app.timeline.clock import ClockOffset, CorrectionMethod

logger = logging.getLogger(__name__)

#: Bytes read for parser sniffing before the full pass.
SNIFF_BYTES = 8192


@dataclass(slots=True)
class ParseReport:
    evidence_id: str
    parse_status: ParseStatus
    parser_id: str | None
    events_produced: int
    records_read: int
    records_skipped: int
    unrecognised: int
    unrecognised_types: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    truncated: bool = False
    truncation_reason: str = ""
    detail: str = ""


class ParseService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        store: ObjectStore,
        events: EventStore,
        audit: AuditService,
        settings: Settings,
        search: SearchBackend | None = None,
        parsers: ParserRegistry | None = None,
    ) -> None:
        self.session = session
        self.store = store
        self.events = events
        self.audit = audit
        self.settings = settings
        self.search = search
        self.parsers = parsers or default_registry

    async def parse_evidence(
        self,
        evidence_id: str,
        principal: Principal,
        *,
        force: bool = False,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> ParseReport:
        evidence = await EvidenceService(
            self.session, store=self.store, audit=self.audit, settings=self.settings
        ).get(evidence_id, principal)

        if evidence.parse_status == ParseStatus.PARSED and not force:
            raise Conflict(
                f"Evidence {evidence_id} is already parsed. Pass force=true to re-parse "
                f"(existing events for this artifact are replaced, not duplicated)."
            )

        report = await self._run(evidence)

        evidence.parse_status = report.parse_status
        evidence.parse_detail = report.detail
        await self.audit.record(
            action=AuditAction.PARSE,
            principal=principal,
            case_id=evidence.case_id,
            evidence_id=evidence.evidence_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={
                "parser_id": report.parser_id,
                "events_produced": report.events_produced,
                "records_read": report.records_read,
                "records_skipped": report.records_skipped,
                "unrecognised": report.unrecognised,
                "status": str(report.parse_status),
                "truncated": report.truncated,
            },
        )
        await self.session.commit()
        await self.audit.flush_mirror()
        return report

    async def _run(self, evidence: Evidence) -> ParseReport:
        try:
            head = await self._read_head(evidence)
        except ObjectNotFound:
            return ParseReport(
                evidence_id=evidence.evidence_id,
                parse_status=ParseStatus.FAILED,
                parser_id=None,
                events_produced=0,
                records_read=0,
                records_skipped=0,
                unrecognised=0,
                detail="The stored object is missing from the evidence bucket.",
            )

        source_type = SourceType(evidence.source_type)
        parser = self.parsers.select(source_type, head)
        if parser is None:
            return ParseReport(
                evidence_id=evidence.evidence_id,
                parse_status=ParseStatus.UNSUPPORTED,
                parser_id=None,
                events_produced=0,
                records_read=0,
                records_skipped=0,
                unrecognised=0,
                detail=(
                    f"No parser handles source_type={evidence.source_type} and no parser "
                    f"recognised the content. The artifact is stored and verifiable; it is "
                    f"simply not normalized."
                ),
            )

        context = ParseContext(
            evidence_id=evidence.evidence_id,
            case_id=evidence.case_id,
            tenant_id=evidence.tenant_id,
            source=evidence.source,
            source_type=source_type,
            clock_offset=self._clock_offset(evidence),
            limits=ReadLimits(
                max_records=self.settings.parse_max_records,
                max_bytes=self.settings.parse_max_bytes,
                max_record_bytes=self.settings.parse_max_record_bytes,
            ),
        )

        stream = self.store.stream(
            evidence.storage_bucket,
            evidence.storage_key,
            chunk_size=self.settings.evidence_read_chunk_bytes,
        )
        outcome = await parser.parse(stream, context)

        # Replace rather than append, so re-parsing cannot duplicate a timeline.
        await self.events.delete_for_evidence(evidence.tenant_id, evidence.evidence_id)
        written = await self.events.insert_events(outcome.events)

        # The search index is derived data. If it fails, the events are still
        # in the store and the index can be rebuilt — so this is logged, not
        # fatal. Failing the parse would lose more than it protects.
        index_warning = ""
        if self.search is not None and outcome.events:
            try:
                await self.search.remove_evidence(evidence.tenant_id, evidence.evidence_id)
                await self.search.index_events(outcome.events)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Search indexing failed for %s: %s", evidence.evidence_id, exc
                )
                index_warning = (
                    f" Search indexing FAILED ({exc.__class__.__name__}); events are in "
                    f"the store and the index can be rebuilt."
                )

        status = ParseStatus.PARSED
        if not outcome.events and outcome.stats.records_read:
            # Records were read but nothing mapped: honest, and not a success.
            status = ParseStatus.UNSUPPORTED

        detail = (
            f"{parser.parser_id}: {written} event(s) from {outcome.stats.records_read} record(s)."
        )
        if outcome.stats.records_skipped:
            detail += f" {outcome.stats.records_skipped} malformed record(s) skipped."
        if outcome.unrecognised:
            top = ", ".join(
                f"{kind} x{count}"
                for kind, count in sorted(
                    outcome.unrecognised_types.items(), key=lambda item: -item[1]
                )[:5]
            )
            detail += f" {outcome.unrecognised} unrecognised record(s): {top}."
        if outcome.stats.truncated:
            detail += f" TRUNCATED: {outcome.stats.truncation_reason}."
        if outcome.errors:
            detail += f" {len(outcome.errors)} record error(s)."
        detail += index_warning

        return ParseReport(
            evidence_id=evidence.evidence_id,
            parse_status=status,
            parser_id=parser.parser_id,
            events_produced=written,
            records_read=outcome.stats.records_read,
            records_skipped=outcome.stats.records_skipped,
            unrecognised=outcome.unrecognised,
            unrecognised_types=outcome.unrecognised_types,
            errors=outcome.errors[:50],
            truncated=outcome.stats.truncated,
            truncation_reason=outcome.stats.truncation_reason,
            detail=detail,
        )

    async def _read_head(self, evidence: Evidence) -> bytes:
        head = b""
        async for chunk in self.store.stream_range(
            evidence.storage_bucket,
            evidence.storage_key,
            offset=0,
            length=min(SNIFF_BYTES, evidence.size or SNIFF_BYTES),
            chunk_size=SNIFF_BYTES,
        ):
            head += chunk
            if len(head) >= SNIFF_BYTES:
                break
        return head

    @staticmethod
    def _clock_offset(evidence: Evidence) -> ClockOffset | None:
        """The offset the collector reported for this artifact, if any.

        ``None`` means "no correction", which is different from "zero offset":
        the first leaves ``method=NONE`` and confidence 1.0 on the event, the
        second would claim a measurement nobody made.
        """
        if not evidence.clock_offset_seconds:
            return None
        try:
            method = CorrectionMethod(evidence.clock_offset_method or "COLLECTOR_DELTA")
        except ValueError:
            method = CorrectionMethod.COLLECTOR_DELTA
        return ClockOffset(
            source=evidence.source,
            offset_seconds=float(evidence.clock_offset_seconds),
            confidence=float(evidence.clock_offset_confidence or 1.0),
            method=method,
        )


async def read_raw_record(
    store: ObjectStore, evidence: Evidence, reference: str, *, max_bytes: int
) -> bytes:
    """Fetch the exact bytes a normalized event came from.

    The final hop of the provenance chain: an analyst clicking a finding can
    see the original record, not a re-rendering of it.
    """
    from app.normalization.reference import InvalidRawReference, RawReference  # noqa: PLC0415

    try:
        locator = RawReference.parse(reference)
    except InvalidRawReference as exc:
        raise NotFound(str(exc)) from exc

    if locator.length > max_bytes:
        raise NotFound(
            f"Record locator spans {locator.length} bytes, above the {max_bytes} byte limit."
        )
    if evidence.size and locator.end > evidence.size:
        raise NotFound("Record locator points past the end of the stored object.")

    collected = b""
    async for chunk in store.stream_range(
        evidence.storage_bucket,
        evidence.storage_key,
        offset=locator.offset,
        length=locator.length,
    ):
        collected += chunk
    return collected
