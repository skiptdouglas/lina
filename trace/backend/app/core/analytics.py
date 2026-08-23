"""Analytics store abstraction (ADR-0002).

ClickHouse is the implementation today. An enterprise deployment can provide
a Databricks/Delta implementation of the same interface (§56 of the brief)
without touching route or service code.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import Any

logger = logging.getLogger(__name__)


class AnalyticsStore(ABC):
    """Columnar analytics backend for normalized events and the audit mirror."""

    name: str

    @abstractmethod
    async def ping(self) -> bool:
        """Return True when the backend is reachable."""

    @abstractmethod
    async def apply_schema(self, statements: Iterable[str]) -> None:
        """Apply idempotent DDL statements."""

    @abstractmethod
    async def insert(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        """Append rows. Analytics tables are append-only."""

    @abstractmethod
    async def query(
        self, sql: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run a read query and return rows as dicts."""

    @abstractmethod
    async def close(self) -> None: ...


class NullAnalyticsStore(AnalyticsStore):
    """Used when ClickHouse is disabled or unreachable.

    Reads raise so that a caller can never mistake "no backend" for "no data";
    writes are dropped with a warning because the audit *chain of record* lives
    in the relational store (ADR-0003) and must not be blocked by the mirror.
    """

    name = "null"

    def __init__(self, reason: str = "analytics backend disabled") -> None:
        self.reason = reason

    async def ping(self) -> bool:
        return False

    async def apply_schema(self, statements: Iterable[str]) -> None:
        logger.warning("Skipping analytics schema: %s", self.reason)

    async def insert(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        logger.warning("Dropping %d row(s) for %s: %s", len(rows), table, self.reason)

    async def query(
        self, sql: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        raise RuntimeError(f"Analytics queries are unavailable: {self.reason}")

    async def close(self) -> None:
        return None
