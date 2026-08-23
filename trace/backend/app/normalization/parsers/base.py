"""Parser plugin framework.

A parser turns one artifact into normalized events. Three rules bind every
implementation:

1. **It reads a fresh copy from object storage.** Never the upload stream — the
   raw artifact must survive parsing untouched (ADR-0005).
2. **Every event carries provenance.** ``evidence_id`` and a byte-accurate
   ``raw_reference`` are mandatory; an event that cannot be walked back to its
   original bytes must never reach the event store.
3. **Original timestamps are never overwritten.** A parser sets
   ``original_timestamp`` from the source verbatim; clock correction is applied
   separately and recorded alongside it (brief §17).

Most sources are JSON lines, so :class:`JsonLinesParser` handles the streaming,
byte arithmetic, limits and error accounting, and subclasses implement one
method: turn a decoded record into an event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

from app.core.ids import new_event_id
from app.evidence.enums import SourceType
from app.normalization.jsonl import RawRecord, ReadLimits, ReadStats, iter_json_records
from app.normalization.reference import RawReference
from app.normalization.schema import ClockCorrection, NormalizedEvent
from app.timeline.clock import ClockOffset, correct


@dataclass(slots=True)
class ParseContext:
    """Everything a parser needs that is not in the artifact itself."""

    evidence_id: str
    case_id: str
    tenant_id: str
    source: str
    source_type: SourceType
    #: Correction to apply to this artifact's timestamps, if the collector
    #: measured one. ``None`` means "no correction", not "zero offset".
    clock_offset: ClockOffset | None = None
    limits: ReadLimits = field(default_factory=ReadLimits)


@dataclass(slots=True)
class ParseOutcome:
    events: list[NormalizedEvent] = field(default_factory=list)
    stats: ReadStats = field(default_factory=ReadStats)
    #: Records the parser read but did not recognise — reported, not hidden.
    unrecognised: int = 0
    #: Distinct record types seen but not mapped, for the parse report.
    unrecognised_types: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def note_unrecognised(self, kind: str) -> None:
        self.unrecognised += 1
        self.unrecognised_types[kind] = self.unrecognised_types.get(kind, 0) + 1


class Parser(ABC):
    """Turns raw bytes into normalized events."""

    #: Stable identifier, e.g. ``sysmon-json``.
    parser_id: str
    #: Source types this parser claims.
    handles: tuple[SourceType, ...] = ()
    #: Record types the parser understands, for the capability report.
    supported_records: tuple[str, ...] = ()
    description: str = ""

    @abstractmethod
    def sniff(self, head: bytes) -> bool:
        """Cheap check against the first bytes of an artifact."""

    @abstractmethod
    async def parse(
        self, stream: AsyncIterator[bytes], context: ParseContext
    ) -> ParseOutcome: ...


class JsonLinesParser(Parser):
    """Base for JSON-lines sources. Subclasses implement :meth:`build_event`."""

    async def parse(
        self, stream: AsyncIterator[bytes], context: ParseContext
    ) -> ParseOutcome:
        outcome = ParseOutcome()
        async for record in iter_json_records(
            stream, limits=context.limits, stats=outcome.stats
        ):
            try:
                event = self.build_event(record, context)
            except Exception as exc:  # noqa: BLE001 - one bad record must not end the parse
                outcome.errors.append(
                    f"line {record.reference.index}: {exc.__class__.__name__}: {exc}"
                )
                continue
            if event is None:
                outcome.note_unrecognised(self.record_kind(record))
                continue
            outcome.events.append(event)
        return outcome

    @abstractmethod
    def build_event(self, record: RawRecord, context: ParseContext) -> NormalizedEvent | None:
        """Return an event, or ``None`` when the record type is not mapped."""

    def record_kind(self, record: RawRecord) -> str:
        """Label used to report unrecognised records."""
        return "unknown"

    # ---- helpers shared by concrete parsers --------------------------------
    @staticmethod
    def make_event(
        *,
        context: ParseContext,
        reference: RawReference,
        original_timestamp: datetime,
        event_type: str,
        **fields,
    ) -> NormalizedEvent:
        """Assemble an event with provenance and clock handling applied.

        The only place events are constructed, so no parser can forget the
        pieces that make an event admissible.
        """
        corrected = correct(original_timestamp, context.clock_offset)
        return NormalizedEvent(
            event_id=new_event_id(),
            timestamp=corrected.corrected_time,
            original_timestamp=corrected.original_time,
            clock=ClockCorrection(
                clock_offset_seconds=corrected.clock_offset,
                correction_confidence=corrected.correction_confidence,
                method=str(corrected.method),
            ),
            event_type=event_type,
            case_id=context.case_id,
            tenant_id=context.tenant_id,
            evidence_id=context.evidence_id,
            raw_reference=reference.to_string(),
            **fields,
        )
