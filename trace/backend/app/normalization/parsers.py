"""Parser plugin framework (Sprint 2).

Parsers are plugins: each declares the source types it handles and yields
:class:`~app.normalization.schema.NormalizedEvent` objects from a *fresh copy*
of the raw artifact. A parser never receives the upload stream (ADR-0005).

No parser is implemented yet — ``registry`` is empty and
``POST /api/v1/ingestion/parse/{id}`` returns 501 rather than pretending an
artifact was parsed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

from app.evidence.enums import SourceType
from app.normalization.schema import NormalizedEvent


@dataclass(slots=True)
class ParseContext:
    evidence_id: str
    case_id: str
    tenant_id: str
    source: str
    source_type: SourceType


class Parser(ABC):
    """Turns raw bytes into normalized events."""

    #: Stable identifier, e.g. ``sysmon-evtx-json``.
    parser_id: str
    #: Source types this parser claims.
    handles: tuple[SourceType, ...] = ()
    #: Sysmon event IDs / record types the parser understands, for reporting.
    supported_records: tuple[str, ...] = ()

    @abstractmethod
    def sniff(self, head: bytes) -> bool:
        """Cheap check on the first bytes of an artifact."""

    @abstractmethod
    def parse(
        self, stream: AsyncIterator[bytes], context: ParseContext
    ) -> AsyncIterator[NormalizedEvent]:
        """Yield events. Must set ``raw_reference`` on every event."""


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: list[Parser] = []

    def register(self, parser: Parser) -> None:
        self._parsers.append(parser)

    def for_source_type(self, source_type: SourceType) -> list[Parser]:
        return [p for p in self._parsers if source_type in p.handles]

    def all(self) -> Iterable[Parser]:
        return tuple(self._parsers)

    def __len__(self) -> int:
        return len(self._parsers)


#: Populated in Sprint 2 with Sysmon (1, 3, 7, 10, 11, 13, 22), Windows
#: Security, Linux JSON, Zeek JSON and Suricata EVE parsers.
registry = ParserRegistry()
