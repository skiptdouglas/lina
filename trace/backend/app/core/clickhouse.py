"""ClickHouse implementation of :class:`AnalyticsStore`."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.core.analytics import AnalyticsStore

logger = logging.getLogger(__name__)


class ClickHouseAnalyticsStore(AnalyticsStore):
    name = "clickhouse"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
    ) -> None:
        self._connect_kwargs = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        }
        self._database = database
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        if self._client is None:
            import clickhouse_connect  # noqa: PLC0415 - optional at import time

            # The database may not exist on first boot, so connect without it and
            # create it as the first DDL statement.
            self._client = await clickhouse_connect.get_async_client(**self._connect_kwargs)
        return self._client

    async def ping(self) -> bool:
        try:
            client = await self._get_client()
            await client.command("SELECT 1")
            return True
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            logger.warning("ClickHouse ping failed: %s", exc)
            return False

    async def apply_schema(self, statements: Iterable[str]) -> None:
        client = await self._get_client()
        for statement in statements:
            sql = statement.strip()
            if sql:
                await client.command(sql)

    async def insert(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        if not rows:
            return
        client = await self._get_client()
        await client.insert(table, rows, column_names=list(columns))

    async def query(
        self, sql: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        result = await client.query(sql, parameters=parameters or {})
        return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def load_schema_statements(schema_dir: Path) -> list[str]:
    """Read ``deploy/clickhouse/*.sql`` in filename order and split on ``;``.

    The files contain only idempotent ``CREATE ... IF NOT EXISTS`` DDL, so
    applying them on every boot is safe.
    """
    statements: list[str] = []
    if not schema_dir.is_dir():
        logger.warning("ClickHouse schema directory not found: %s", schema_dir)
        return statements
    for path in sorted(schema_dir.glob("*.sql")):
        content = path.read_text(encoding="utf-8")
        stripped = "\n".join(
            line for line in content.splitlines() if not line.strip().startswith("--")
        )
        statements.extend(part.strip() for part in stripped.split(";") if part.strip())
    return statements
