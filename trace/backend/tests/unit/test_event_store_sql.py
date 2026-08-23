"""The SQL event store, held to the shared contract."""

from __future__ import annotations

import pytest

from app.events.sql_store import SqlEventStore
from tests.contract.event_store_contract import EventStoreContract


class TestSqlEventStore(EventStoreContract):
    @pytest.fixture
    async def store(self, database) -> SqlEventStore:
        return SqlEventStore(database.session_factory)
