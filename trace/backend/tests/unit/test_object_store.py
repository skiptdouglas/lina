"""ObjectStore contract, exercised through the in-memory implementation."""

from __future__ import annotations

import pytest

from app.evidence.storage import InMemoryObjectStore, ObjectNotFound


async def test_put_stat_stream_delete_round_trip(tmp_path) -> None:
    store = InMemoryObjectStore()
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"abcdef" * 10)

    await store.ensure_bucket("evidence")
    stat = await store.put_file("evidence", "k/1", source, length=60, content_type="text/plain")
    assert stat.size == 60

    collected = b""
    async for chunk in store.stream("evidence", "k/1", chunk_size=7):
        collected += chunk
    assert collected == source.read_bytes()

    await store.delete("evidence", "k/1")
    with pytest.raises(ObjectNotFound):
        await store.stat("evidence", "k/1")


async def test_stream_of_a_missing_object_raises() -> None:
    store = InMemoryObjectStore()
    with pytest.raises(ObjectNotFound):
        async for _ in store.stream("evidence", "absent"):
            pass
