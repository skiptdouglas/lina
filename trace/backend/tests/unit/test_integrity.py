"""Streaming hash and spooling primitives."""

from __future__ import annotations

import hashlib

import pytest

from app.core.errors import PayloadTooLarge
from app.evidence.integrity import hash_path, hash_stream, hashes_match, spool_stream


async def _chunks(data: bytes, size: int):
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]


@pytest.mark.parametrize("chunk_size", [1, 7, 64, 4096])
async def test_stream_hash_matches_hashlib_regardless_of_chunking(chunk_size: int) -> None:
    payload = b"\x00\x01binary evidence \xff" * 500
    digest, size = await hash_stream(_chunks(payload, chunk_size))
    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)


async def test_hash_of_empty_input() -> None:
    digest, size = await hash_stream(_chunks(b"", 8))
    assert digest == hashlib.sha256(b"").hexdigest()
    assert size == 0


async def test_spool_stream_writes_file_and_hashes_it(tmp_path) -> None:
    payload = b"evidence bytes" * 100
    artifact = await spool_stream(_chunks(payload, 13), max_bytes=1_000_000, spool_dir=tmp_path)
    try:
        assert artifact.size == len(payload)
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
        assert artifact.path.read_bytes() == payload
        assert await hash_path(artifact.path) == (artifact.sha256, artifact.size)
    finally:
        artifact.cleanup()
    assert not artifact.path.exists()


async def test_spool_stream_enforces_the_cap_on_received_bytes(tmp_path) -> None:
    payload = b"x" * 5000
    with pytest.raises(PayloadTooLarge):
        await spool_stream(_chunks(payload, 100), max_bytes=1024, spool_dir=tmp_path)
    # No partial artifact is left behind.
    assert list(tmp_path.iterdir()) == []


def test_hashes_match_is_case_insensitive() -> None:
    digest = hashlib.sha256(b"a").hexdigest()
    assert hashes_match(digest, digest.upper())
    assert not hashes_match(digest, "0" * 64)
