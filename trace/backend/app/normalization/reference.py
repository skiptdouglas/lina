"""Record locators — the link from a normalized event back to original bytes.

Every event carries a ``raw_reference`` naming exactly which bytes of which
artifact produced it. That is what makes the "SHOW EVIDENCE" traversal real
rather than aspirational (brief §57): given an event, TRACE can range-read the
original object and hand back the precise record.

Grammar::

    <format>:<index>:<offset>:<length>

    format   how the artifact is segmented (currently always "jsonl")
    index    0-based line number within the artifact (counts blank and
             malformed lines too, so it matches what a text editor shows)
    offset   byte offset of the record's first byte
    length   byte length of the record, excluding the line terminator

Offsets are byte offsets into the *stored object*, not into a decoded string,
so they stay valid regardless of encoding and can be served by an HTTP range
request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FORMAT_JSONL = "jsonl"
_PATTERN = re.compile(
    r"^(?P<format>[a-z0-9_]{1,16}):(?P<index>\d+):(?P<offset>\d+):(?P<length>\d+)$"
)


class InvalidRawReference(ValueError):
    """The reference is not well-formed."""


@dataclass(frozen=True, slots=True)
class RawReference:
    format: str
    index: int
    offset: int
    length: int

    def __post_init__(self) -> None:
        if self.index < 0 or self.offset < 0 or self.length < 0:
            raise InvalidRawReference("Record locator fields must not be negative.")

    def to_string(self) -> str:
        return f"{self.format}:{self.index}:{self.offset}:{self.length}"

    @classmethod
    def parse(cls, value: str) -> RawReference:
        match = _PATTERN.match(value or "")
        if not match:
            raise InvalidRawReference(
                f"Malformed record locator {value!r}; expected format:index:offset:length"
            )
        return cls(
            format=match["format"],
            index=int(match["index"]),
            offset=int(match["offset"]),
            length=int(match["length"]),
        )

    @property
    def end(self) -> int:
        return self.offset + self.length
