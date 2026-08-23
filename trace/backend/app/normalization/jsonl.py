"""Streaming JSON-lines reader that tracks byte offsets.

Every parser TRACE ships reads JSON lines, so the offset arithmetic lives here
once. Getting it wrong would produce references that point at the wrong bytes —
a provenance failure that would only surface when someone tried to verify a
finding, which is the worst possible time.

Constant memory: records are yielded as they complete, and the buffer never
holds more than one oversized record.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.normalization.reference import FORMAT_JSONL, RawReference


@dataclass(slots=True)
class RawRecord:
    """One record plus the locator that can fetch it again."""

    data: dict
    reference: RawReference
    raw: bytes


@dataclass(slots=True)
class ReadLimits:
    """Bounds applied while reading untrusted evidence.

    Evidence is attacker-influenced by definition — it came from a compromised
    machine. A 40 GB single-line file or a billion-record log must degrade into
    a reported limit, not an out-of-memory kill (docs/SECURITY.md §5).
    """

    max_records: int = 5_000_000
    max_bytes: int = 8 * 1024**3
    max_record_bytes: int = 8 * 1024**2


@dataclass(slots=True)
class ReadStats:
    records_read: int = 0
    records_skipped: int = 0
    bytes_read: int = 0
    truncated: bool = False
    truncation_reason: str = ""


async def iter_json_records(
    stream: AsyncIterator[bytes],
    *,
    limits: ReadLimits | None = None,
    stats: ReadStats | None = None,
) -> AsyncIterator[RawRecord]:
    """Yield each JSON object in a JSON-lines stream with its byte locator.

    Malformed lines are counted and skipped rather than aborting the parse: one
    corrupt record in a recovered log should not cost the other 400,000.
    """
    limits = limits or ReadLimits()
    stats = stats if stats is not None else ReadStats()

    buffer = bytearray()
    offset = 0  # byte offset of buffer[0] within the artifact
    index = 0

    async for chunk in stream:
        stats.bytes_read += len(chunk)
        if stats.bytes_read > limits.max_bytes:
            stats.truncated = True
            stats.truncation_reason = f"artifact exceeds {limits.max_bytes} bytes"
            return
        buffer += chunk

        while True:
            newline = buffer.find(b"\n")
            if newline == -1:
                break
            line = bytes(buffer[:newline])
            consumed = newline + 1
            del buffer[:consumed]

            record = _decode(line, index, offset, stats, limits)
            if record is not None:
                yield record
                if stats.records_read >= limits.max_records:
                    stats.truncated = True
                    stats.truncation_reason = f"record limit {limits.max_records} reached"
                    return
            offset += consumed
            index += 1

        if len(buffer) > limits.max_record_bytes:
            # A single record larger than the cap: skip to the next newline
            # rather than buffering it.
            stats.records_skipped += 1
            offset += len(buffer)
            index += 1
            buffer.clear()

    if buffer.strip():
        record = _decode(bytes(buffer), index, offset, stats, limits)
        if record is not None:
            yield record


def _decode(
    line: bytes, index: int, offset: int, stats: ReadStats, limits: ReadLimits
) -> RawRecord | None:
    stripped = line.strip()
    if not stripped:
        return None
    if len(line) > limits.max_record_bytes:
        stats.records_skipped += 1
        return None
    try:
        data = json.loads(stripped.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        stats.records_skipped += 1
        return None
    if not isinstance(data, dict):
        stats.records_skipped += 1
        return None

    stats.records_read += 1
    return RawRecord(
        data=data,
        # length excludes the newline but keeps a CR, so the locator addresses
        # exactly the bytes the record occupies in the stored object.
        reference=RawReference(FORMAT_JSONL, index, offset, len(line)),
        raw=line,
    )
