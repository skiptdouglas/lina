"""Real MinIO round trip.

Skipped unless a MinIO endpoint is reachable, so the suite stays runnable
without infrastructure:

    TRACE_MINIO_ENDPOINT=localhost:9000 \
    TRACE_MINIO_ACCESS_KEY=... TRACE_MINIO_SECRET_KEY=... \
    pytest -m integration
"""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest

from app.evidence.integrity import hash_stream
from app.evidence.storage import MinioObjectStore, ObjectNotFound

pytestmark = pytest.mark.integration

ENDPOINT = os.getenv("TRACE_MINIO_ENDPOINT", "")
ACCESS_KEY = os.getenv("TRACE_MINIO_ACCESS_KEY", "")
SECRET_KEY = os.getenv("TRACE_MINIO_SECRET_KEY", "")


@pytest.fixture
async def store() -> MinioObjectStore:
    if not (ENDPOINT and ACCESS_KEY and SECRET_KEY):
        pytest.skip("MinIO credentials are not configured; set TRACE_MINIO_* to run.")
    candidate = MinioObjectStore(
        endpoint=ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=False
    )
    if not await candidate.ping():
        pytest.skip(f"MinIO at {ENDPOINT} is unreachable.")
    return candidate


async def test_round_trip_preserves_bytes_and_digest(store, tmp_path) -> None:
    bucket = "trace-test"
    key = f"integration/{uuid.uuid4().hex}/artifact.bin"
    payload = os.urandom(256 * 1024)
    source = tmp_path / "artifact.bin"
    source.write_bytes(payload)

    await store.ensure_bucket(bucket)
    stat = await store.put_file(bucket, key, source, length=len(payload))
    assert stat.size == len(payload)

    digest, size = await hash_stream(store.stream(bucket, key, chunk_size=64 * 1024))
    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)

    await store.delete(bucket, key)
    with pytest.raises(ObjectNotFound):
        await store.stat(bucket, key)


async def test_missing_object_raises_object_not_found(store) -> None:
    with pytest.raises(ObjectNotFound):
        await store.stat("trace-test", f"absent/{uuid.uuid4().hex}")
