"""Hashing and spooling primitives.

Everything here is constant-memory: TRACE must be able to ingest a 40 GB
memory image on a container with 512 MB of RAM.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import PayloadTooLarge

HASH_ALGORITHM = "sha256"
DEFAULT_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class SpooledArtifact:
    """An upload written to local disk, hashed on the way past."""

    path: Path
    sha256: str
    size: int

    def cleanup(self) -> None:
        self.path.unlink(missing_ok=True)


def hash_path_sync(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


async def hash_path(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[str, int]:
    return await asyncio.to_thread(hash_path_sync, path, chunk_size)


async def hash_stream(stream: AsyncIterator[bytes]) -> tuple[str, int]:
    """Hash an async byte stream without buffering it."""
    digest = hashlib.sha256()
    size = 0
    async for chunk in stream:
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


async def spool_stream(
    stream: AsyncIterator[bytes],
    *,
    max_bytes: int,
    spool_dir: Path | None = None,
) -> SpooledArtifact:
    """Stream an upload to a temporary file, hashing as it is written.

    The size cap is enforced against the bytes actually received, not against
    a client-supplied ``Content-Length`` header.
    """
    if spool_dir is not None:
        await asyncio.to_thread(spool_dir.mkdir, parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed explicitly below
        delete=False, dir=str(spool_dir) if spool_dir else None, prefix="trace-upload-"
    )
    path = Path(handle.name)
    digest = hashlib.sha256()
    size = 0
    try:
        async for chunk in stream:
            size += len(chunk)
            if size > max_bytes:
                raise PayloadTooLarge(
                    f"Upload exceeds the configured maximum of {max_bytes} bytes."
                )
            digest.update(chunk)
            await asyncio.to_thread(handle.write, chunk)
    except BaseException:
        handle.close()
        await asyncio.to_thread(path.unlink, True)
        raise
    handle.close()
    return SpooledArtifact(path=path, sha256=digest.hexdigest(), size=size)


def hashes_match(expected: str, actual: str) -> bool:
    """Case-insensitive constant-time-ish comparison of hex digests."""
    import secrets  # noqa: PLC0415

    return secrets.compare_digest(expected.lower(), actual.lower())
