"""Metadata database access (ADR-0003).

SQLAlchemy 2.0 async. ``TRACE_DATABASE_URL`` selects the backend:
``sqlite+aiosqlite`` for the MVP, ``postgresql+asyncpg`` for production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, TypeDecorator, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetimes, normalised to UTC in both directions."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime()}


class Database:
    """Owns the engine and session factory for the metadata store."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self._prepare_sqlite_path(url)
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, future=True)
        if url.startswith("sqlite"):
            self._enable_sqlite_pragmas()
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    @staticmethod
    def _prepare_sqlite_path(url: str) -> None:
        if not url.startswith("sqlite"):
            return
        _, _, path = url.partition("///")
        if path and path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    def _enable_sqlite_pragmas(self) -> None:
        @event.listens_for(self.engine.sync_engine, "connect")
        def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async def create_all(self) -> None:
        # Importing the aggregate module registers every table on Base.metadata.
        from app import models  # noqa: F401,PLC0415

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session
