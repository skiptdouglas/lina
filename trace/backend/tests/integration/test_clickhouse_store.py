"""The ClickHouse store, held to the same contract as the SQL one.

Skipped unless a ClickHouse server is reachable, so the suite stays runnable
without infrastructure:

    TRACE_CLICKHOUSE_HOST=localhost TRACE_CLICKHOUSE_USER=trace \
    TRACE_CLICKHOUSE_PASSWORD=... pytest -m integration

The point of running the *same* class against both backends is that a second
implementation cannot quietly diverge from the first.
"""

from __future__ import annotations

import os

import pytest

from app.core.clickhouse import ClickHouseAnalyticsStore, load_schema_statements
from app.events.clickhouse_store import ClickHouseEventStore
from tests.contract.event_store_contract import EventStoreContract

pytestmark = pytest.mark.integration

SCHEMA_DIR = __import__("pathlib").Path(__file__).resolve().parents[3] / "deploy" / "clickhouse"


class TestClickHouseEventStore(EventStoreContract):
    @pytest.fixture
    async def store(self):
        host = os.getenv("TRACE_CLICKHOUSE_HOST", "")
        if not host:
            pytest.skip("TRACE_CLICKHOUSE_HOST is not set; skipping ClickHouse contract run.")
        analytics = ClickHouseAnalyticsStore(
            host=host,
            port=int(os.getenv("TRACE_CLICKHOUSE_PORT", "8123")),
            username=os.getenv("TRACE_CLICKHOUSE_USER", "trace"),
            password=os.getenv("TRACE_CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("TRACE_CLICKHOUSE_DATABASE", "trace"),
        )
        if not await analytics.ping():
            pytest.skip(f"ClickHouse at {host} is unreachable.")
        await analytics.apply_schema(load_schema_statements(SCHEMA_DIR))

        candidate = ClickHouseEventStore(analytics)
        # Each contract test needs an empty table; scope by wiping the tenants
        # the contract uses. Mutations are async, so wait for them to settle.
        for tenant in ("default", "other-tenant"):
            await analytics.query(
                "ALTER TABLE trace.events DELETE WHERE tenant_id = {t:String} "
                "SETTINGS mutations_sync = 2",
                {"t": tenant},
            )
        try:
            yield candidate
        finally:
            for tenant in ("default", "other-tenant"):
                await analytics.query(
                    "ALTER TABLE trace.events DELETE WHERE tenant_id = {t:String} "
                    "SETTINGS mutations_sync = 2",
                    {"t": tenant},
                )
            await analytics.close()


@pytest.mark.integration
async def test_clickhouse_schema_statements_parse() -> None:
    """The DDL must at least be well-formed even when no server is present."""
    statements = load_schema_statements(SCHEMA_DIR)
    assert statements, "no ClickHouse DDL found"
    assert any("trace.events" in s for s in statements)
    assert all(s.strip() for s in statements)
    # Nullability decision from docs/DATA_MODEL.md must survive edits.
    events_ddl = next(s for s in statements if "CREATE TABLE IF NOT EXISTS trace.events" in s)
    for column in ("src_port", "dst_port", "process_pid", "parent_pid", "file_size"):
        assert f"{column}" in events_ddl
        assert "Nullable" in events_ddl
