"""Parser registry.

Dispatch is by declared ``source_type`` first — the collector knows what it
collected — and by content sniffing as a fallback, because analysts mislabel
uploads and a wrong label should degrade into "let me look at the bytes"
rather than "no parser".
"""

from __future__ import annotations

from collections.abc import Iterable

from app.evidence.enums import SourceType
from app.normalization.parsers.base import (
    JsonLinesParser,
    ParseContext,
    ParseOutcome,
    Parser,
)
from app.normalization.parsers.linux_json import LinuxJsonParser
from app.normalization.parsers.suricata import SuricataParser
from app.normalization.parsers.sysmon import SysmonParser
from app.normalization.parsers.windows_security import WindowsSecurityParser
from app.normalization.parsers.zeek import ZeekParser


class ParserRegistry:
    def __init__(self, parsers: Iterable[Parser] = ()) -> None:
        self._parsers: list[Parser] = list(parsers)

    def register(self, parser: Parser) -> None:
        self._parsers.append(parser)

    def all(self) -> tuple[Parser, ...]:
        return tuple(self._parsers)

    def by_id(self, parser_id: str) -> Parser | None:
        return next((p for p in self._parsers if p.parser_id == parser_id), None)

    def for_source_type(self, source_type: SourceType) -> list[Parser]:
        return [p for p in self._parsers if source_type in p.handles]

    def select(self, source_type: SourceType, head: bytes) -> Parser | None:
        """Pick a parser for an artifact.

        Declared type wins, but only if the parser also recognises the content —
        otherwise a Zeek log uploaded as ``SYSMON`` would be handed to the
        Sysmon parser and produce nothing.
        """
        declared = self.for_source_type(source_type)
        for parser in declared:
            if parser.sniff(head):
                return parser
        for parser in self._parsers:
            if parser.sniff(head):
                return parser
        # Fall back to the declared parser even without a content match, so the
        # failure is reported as "parsed 0 records" rather than "no parser".
        return declared[0] if declared else None

    def __len__(self) -> int:
        return len(self._parsers)


#: The parsers TRACE ships.
registry = ParserRegistry(
    [
        SysmonParser(),
        WindowsSecurityParser(),
        ZeekParser(),
        SuricataParser(),
        LinuxJsonParser(),
    ]
)

__all__ = [
    "JsonLinesParser",
    "LinuxJsonParser",
    "ParseContext",
    "ParseOutcome",
    "Parser",
    "ParserRegistry",
    "SuricataParser",
    "SysmonParser",
    "WindowsSecurityParser",
    "ZeekParser",
    "registry",
]
