"""Object storage for raw evidence.

The interface is deliberately small and S3-shaped so that MinIO, AWS S3 or
any other S3-compatible store is a configuration change (ADR-0005).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1024 * 1024


class ObjectNotFound(Exception):
    """The requested object does not exist in the store."""


@dataclass(frozen=True, slots=True)
class ObjectStat:
    bucket: str
    key: str
    size: int
    etag: str | None = None
    content_type: str | None = None
    last_modified: datetime | None = None


class ObjectStore(ABC):
    """Raw evidence storage. Objects written here are never modified."""

    name: str

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def ensure_bucket(self, bucket: str) -> None: ...

    @abstractmethod
    async def put_file(
        self,
        bucket: str,
        key: str,
        path: Path,
        *,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> ObjectStat:
        """Upload a file already spooled to local disk."""

    @abstractmethod
    async def stat(self, bucket: str, key: str) -> ObjectStat:
        """Raise :class:`ObjectNotFound` when the object is absent."""

    @abstractmethod
    def stream(
        self, bucket: str, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        """Yield the object's bytes. Raises :class:`ObjectNotFound`."""

    @abstractmethod
    def stream_range(
        self,
        bucket: str,
        key: str,
        *,
        offset: int,
        length: int,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """Yield ``length`` bytes starting at ``offset``.

        This is what turns a normalized event's ``raw_reference`` back into the
        original record without downloading the whole artifact — the last link
        of the "SHOW EVIDENCE" chain (brief §57).
        """

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> None: ...


class MinioObjectStore(ObjectStore):
    """MinIO / S3 implementation.

    The MinIO SDK is synchronous; calls run in a worker thread so the event
    loop is never blocked by object I/O.
    """

    name = "minio"

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        region: str | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        self._region = region
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from minio import Minio  # noqa: PLC0415 - keeps the SDK optional at import

            self._client = Minio(
                self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
                region=self._region,
            )
        return self._client

    @staticmethod
    def _is_missing(exc: Exception) -> bool:
        code = getattr(exc, "code", "")
        return code in {"NoSuchKey", "NoSuchBucket", "ResourceNotFound"}

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._get_client().list_buckets)
            return True
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            logger.warning("Object store ping failed: %s", exc)
            return False

    async def ensure_bucket(self, bucket: str) -> None:
        client = self._get_client()

        def _ensure() -> None:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

        await asyncio.to_thread(_ensure)

    async def put_file(
        self,
        bucket: str,
        key: str,
        path: Path,
        *,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> ObjectStat:
        client = self._get_client()

        def _put() -> None:
            with path.open("rb") as handle:
                client.put_object(bucket, key, handle, length=length, content_type=content_type)

        await asyncio.to_thread(_put)
        return await self.stat(bucket, key)

    async def stat(self, bucket: str, key: str) -> ObjectStat:
        client = self._get_client()
        try:
            info = await asyncio.to_thread(client.stat_object, bucket, key)
        except Exception as exc:  # noqa: BLE001 - mapped to a domain error below
            if self._is_missing(exc):
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise
        return ObjectStat(
            bucket=bucket,
            key=key,
            size=info.size or 0,
            etag=info.etag,
            content_type=info.content_type,
            last_modified=info.last_modified,
        )

    async def stream(
        self, bucket: str, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        client = self._get_client()
        try:
            response = await asyncio.to_thread(client.get_object, bucket, key)
        except Exception as exc:  # noqa: BLE001 - mapped to a domain error below
            if self._is_missing(exc):
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise
        try:
            while True:
                chunk = await asyncio.to_thread(response.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(response.close)
            await asyncio.to_thread(response.release_conn)

    async def stream_range(
        self,
        bucket: str,
        key: str,
        *,
        offset: int,
        length: int,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        if length <= 0:
            return
        client = self._get_client()
        try:
            response = await asyncio.to_thread(
                client.get_object, bucket, key, offset=offset, length=length
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a domain error below
            if self._is_missing(exc):
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise
        try:
            remaining = length
            while remaining > 0:
                chunk = await asyncio.to_thread(response.read, min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(response.close)
            await asyncio.to_thread(response.release_conn)

    async def delete(self, bucket: str, key: str) -> None:
        client = self._get_client()
        await asyncio.to_thread(client.remove_object, bucket, key)


class InMemoryObjectStore(ObjectStore):
    """Test double. Refused in staging/prod by :class:`~app.core.config.Settings`."""

    name = "memory"

    def __init__(self) -> None:
        self._buckets: set[str] = set()
        self._objects: dict[tuple[str, str], bytes] = {}
        self._content_types: dict[tuple[str, str], str] = {}

    async def ping(self) -> bool:
        return True

    async def ensure_bucket(self, bucket: str) -> None:
        self._buckets.add(bucket)

    async def put_file(
        self,
        bucket: str,
        key: str,
        path: Path,
        *,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> ObjectStat:
        data = await asyncio.to_thread(path.read_bytes)
        return await self.put_bytes(bucket, key, data, content_type=content_type)

    async def put_bytes(
        self, bucket: str, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> ObjectStat:
        """Also used by tests to simulate tampering with stored evidence."""
        self._buckets.add(bucket)
        self._objects[(bucket, key)] = data
        self._content_types[(bucket, key)] = content_type
        return await self.stat(bucket, key)

    async def stat(self, bucket: str, key: str) -> ObjectStat:
        if (bucket, key) not in self._objects:
            raise ObjectNotFound(f"{bucket}/{key}")
        data = self._objects[(bucket, key)]
        return ObjectStat(
            bucket=bucket,
            key=key,
            size=len(data),
            content_type=self._content_types.get((bucket, key)),
        )

    async def stream(
        self, bucket: str, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        if (bucket, key) not in self._objects:
            raise ObjectNotFound(f"{bucket}/{key}")
        data = self._objects[(bucket, key)]
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    async def stream_range(
        self,
        bucket: str,
        key: str,
        *,
        offset: int,
        length: int,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        if (bucket, key) not in self._objects:
            raise ObjectNotFound(f"{bucket}/{key}")
        if length <= 0:
            return
        segment = self._objects[(bucket, key)][offset : offset + length]
        for start in range(0, len(segment), chunk_size):
            yield segment[start : start + chunk_size]

    async def delete(self, bucket: str, key: str) -> None:
        self._objects.pop((bucket, key), None)
        self._content_types.pop((bucket, key), None)
