"""Behavioural contract every :class:`EventStore` must satisfy.

Written once against the interface and run against every implementation, so a
second backend cannot quietly diverge from the first. The SQL store runs it in
the unit suite; ClickHouse runs the same class in the integration suite when a
server is reachable.

Subclass, provide ``store``, and the whole contract applies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.events.store import EventQuery, EventStore
from app.normalization.schema import (
    ClockCorrection,
    DeviceRef,
    EventCategory,
    FileRef,
    NetworkEndpoint,
    NetworkRef,
    NormalizedEvent,
    ProcessRef,
    UserRef,
)

BASE = datetime(2026, 8, 20, 8, 45, tzinfo=UTC)
TENANT = "default"
CASE = "CASE-DEMO-001"


def make_event(
    index: int = 0,
    *,
    event_type: str = "PROCESS_CREATE",
    category: EventCategory = EventCategory.PROCESS,
    tenant_id: str = TENANT,
    case_id: str = CASE,
    **overrides,
) -> NormalizedEvent:
    payload = {
        "event_id": f"EVT-{index:032d}",
        "timestamp": BASE + timedelta(seconds=index),
        "original_timestamp": BASE + timedelta(seconds=index),
        "event_type": event_type,
        "category": category,
        "severity": 3,
        "case_id": case_id,
        "tenant_id": tenant_id,
        "user": UserRef(name="jsmith", domain="EXAMPLE"),
        "device": DeviceRef(hostname="FINANCE-LAPTOP-07", ip=["10.20.30.55"]),
        "source": NetworkEndpoint(ip="10.20.30.55", port=51344),
        "destination": NetworkEndpoint(ip="203.0.113.47", port=443, domain="cdn.example"),
        "process": ProcessRef(
            pid=6612,
            name="powershell.exe",
            path="C:\\Windows\\System32\\powershell.exe",
            command_line="powershell -enc SQBFAFgA",
            parent_name="WINWORD.EXE",
        ),
        "file": FileRef(name="updater.exe", path="C:\\Users\\x\\updater.exe", sha256="a" * 64),
        "network": NetworkRef(protocol="tcp", direction="outbound", bytes_out=812),
        "raw_reference": f"jsonl:{index}:0:120",
        "evidence_id": "EVD-contract",
    }
    payload.update(overrides)
    return NormalizedEvent(**payload)


class EventStoreContract:
    """Mix-in providing the contract. Implementations supply a ``store`` fixture."""

    @pytest.fixture
    async def store(self) -> EventStore:  # pragma: no cover - overridden
        raise NotImplementedError

    # ---- round trip --------------------------------------------------------
    async def test_insert_and_retrieve_preserves_every_field(self, store: EventStore) -> None:
        original = make_event(1)
        assert await store.insert_events([original]) == 1

        restored = await store.get_event(TENANT, original.event_id)
        assert restored is not None
        assert restored.model_dump(mode="json") == original.model_dump(mode="json")

    async def test_inserting_nothing_is_a_no_op(self, store: EventStore) -> None:
        assert await store.insert_events([]) == 0

    async def test_unknown_event_returns_none(self, store: EventStore) -> None:
        assert await store.get_event(TENANT, "EVT-absent") is None

    async def test_clock_correction_survives_the_round_trip(self, store: EventStore) -> None:
        """Original timestamps are never overwritten (brief §17)."""
        original_time = BASE
        corrected = BASE + timedelta(seconds=42)
        event = make_event(
            2,
            timestamp=corrected,
            original_timestamp=original_time,
            clock=ClockCorrection(
                clock_offset_seconds=42.0, correction_confidence=0.8, method="COLLECTOR_DELTA"
            ),
        )
        await store.insert_events([event])

        restored = await store.get_event(TENANT, event.event_id)
        assert restored is not None
        assert restored.original_timestamp == original_time
        assert restored.timestamp == corrected
        assert restored.clock.clock_offset_seconds == 42.0
        assert restored.clock.correction_confidence == 0.8
        assert restored.clock.method == "COLLECTOR_DELTA"

    # ---- filtering ---------------------------------------------------------
    async def test_tenant_isolation(self, store: EventStore) -> None:
        await store.insert_events(
            [make_event(10), make_event(11, tenant_id="other-tenant", case_id="CASE-OTHER")]
        )
        mine = await store.search(EventQuery(tenant_id=TENANT))
        assert {e.event_id for e in mine.events} == {make_event(10).event_id}

        theirs = await store.search(EventQuery(tenant_id="other-tenant"))
        assert theirs.total == 1
        assert await store.get_event(TENANT, make_event(11).event_id) is None

    async def test_filter_by_case(self, store: EventStore) -> None:
        await store.insert_events([make_event(20), make_event(21, case_id="CASE-0002")])
        page = await store.search(EventQuery(tenant_id=TENANT, case_id="CASE-0002"))
        assert page.total == 1
        assert page.events[0].case_id == "CASE-0002"

    async def test_filter_by_time_range(self, store: EventStore) -> None:
        await store.insert_events([make_event(i) for i in range(30, 35)])
        page = await store.search(
            EventQuery(
                tenant_id=TENANT,
                time_from=BASE + timedelta(seconds=31),
                time_to=BASE + timedelta(seconds=33),
            )
        )
        assert page.total == 3

    async def test_filter_by_event_type_and_category(self, store: EventStore) -> None:
        await store.insert_events(
            [
                make_event(40),
                make_event(41, event_type="NETWORK_CONNECT", category=EventCategory.NETWORK),
            ]
        )
        by_type = await store.search(
            EventQuery(tenant_id=TENANT, event_types=("NETWORK_CONNECT",))
        )
        assert by_type.total == 1
        by_category = await store.search(EventQuery(tenant_id=TENANT, categories=("PROCESS",)))
        assert by_category.total == 1

    async def test_filter_by_severity_floor(self, store: EventStore) -> None:
        await store.insert_events([make_event(50, severity=1), make_event(51, severity=8)])
        page = await store.search(EventQuery(tenant_id=TENANT, min_severity=5))
        assert page.total == 1
        assert page.events[0].severity == 8

    async def test_filter_by_user_host_process_and_domain(self, store: EventStore) -> None:
        await store.insert_events([make_event(60)])
        for query in (
            EventQuery(tenant_id=TENANT, user="jsmith"),
            EventQuery(tenant_id=TENANT, hostname="FINANCE"),
            EventQuery(tenant_id=TENANT, process="powershell"),
            EventQuery(tenant_id=TENANT, domain="cdn.example"),
            EventQuery(tenant_id=TENANT, command_line="-enc"),
        ):
            assert (await store.search(query)).total == 1, query

    async def test_filter_by_ip_matches_source_or_destination(self, store: EventStore) -> None:
        await store.insert_events([make_event(70)])
        assert (await store.search(EventQuery(tenant_id=TENANT, ip="203.0.113.47"))).total == 1
        assert (await store.search(EventQuery(tenant_id=TENANT, ip="10.20.30.55"))).total == 1
        assert (await store.search(EventQuery(tenant_id=TENANT, ip="8.8.8.8"))).total == 0

    async def test_filter_by_hash_matches_file_or_process(self, store: EventStore) -> None:
        await store.insert_events([make_event(80)])
        page = await store.search(EventQuery(tenant_id=TENANT, file_hash="A" * 64))
        assert page.total == 1, "hash matching must be case-insensitive"

    async def test_filter_by_evidence_id(self, store: EventStore) -> None:
        await store.insert_events([make_event(90), make_event(91, evidence_id="EVD-other")])
        page = await store.search(EventQuery(tenant_id=TENANT, evidence_id="EVD-other"))
        assert page.total == 1

    async def test_free_text_matches_the_command_line(self, store: EventStore) -> None:
        await store.insert_events([make_event(100), make_event(101, process=ProcessRef(name="cmd.exe"))])
        page = await store.search(EventQuery(tenant_id=TENANT, text="powershell"))
        assert page.total == 1
        assert "powershell" in (page.events[0].process.command_line or "").lower()

    async def test_entity_filter_matches_exactly(self, store: EventStore) -> None:
        await store.insert_events([make_event(110)])
        assert (
            await store.search(EventQuery(tenant_id=TENANT, entity="FINANCE-LAPTOP-07"))
        ).total == 1
        assert (await store.search(EventQuery(tenant_id=TENANT, entity="FINANCE"))).total == 0

    # ---- ordering and paging ----------------------------------------------
    async def test_default_order_is_newest_first(self, store: EventStore) -> None:
        await store.insert_events([make_event(i) for i in range(120, 125)])
        page = await store.search(EventQuery(tenant_id=TENANT))
        stamps = [e.timestamp for e in page.events]
        assert stamps == sorted(stamps, reverse=True)

    async def test_ascending_order_for_timelines(self, store: EventStore) -> None:
        await store.insert_events([make_event(i) for i in range(130, 135)])
        page = await store.search(EventQuery(tenant_id=TENANT, ascending=True))
        stamps = [e.timestamp for e in page.events]
        assert stamps == sorted(stamps)

    async def test_paging_covers_every_event_exactly_once(self, store: EventStore) -> None:
        await store.insert_events([make_event(i) for i in range(140, 152)])
        seen: list[str] = []
        for offset in range(0, 12, 5):
            page = await store.search(
                EventQuery(tenant_id=TENANT, limit=5, offset=offset, ascending=True)
            )
            assert page.total == 12
            seen.extend(e.event_id for e in page.events)
        assert len(seen) == 12
        assert len(set(seen)) == 12

    async def test_page_reports_limit_offset_and_backend(self, store: EventStore) -> None:
        await store.insert_events([make_event(160)])
        page = await store.search(EventQuery(tenant_id=TENANT, limit=7, offset=0))
        assert page.limit == 7
        assert page.offset == 0
        assert page.backend == store.name

    # ---- aggregation and counts -------------------------------------------
    async def test_count_for_case(self, store: EventStore) -> None:
        await store.insert_events([make_event(i) for i in range(170, 174)])
        assert await store.count_for_case(TENANT, CASE) == 4
        assert await store.count_for_case(TENANT, "CASE-NOPE") == 0

    async def test_top_values_aggregates_in_the_store(self, store: EventStore) -> None:
        await store.insert_events(
            [make_event(180), make_event(181), make_event(182, process=ProcessRef(name="cmd.exe"))]
        )
        counts = await store.top_values(TENANT, CASE, "process.name", limit=5)
        as_dict = {row.value: row.count for row in counts}
        assert as_dict["powershell.exe"] == 2
        assert as_dict["cmd.exe"] == 1

    async def test_top_values_rejects_an_unknown_dimension(self, store: EventStore) -> None:
        """The dimension reaches SQL, so it comes from an allow-list."""
        with pytest.raises(ValueError, match="not aggregatable"):
            await store.top_values(TENANT, CASE, "process.command_line; DROP TABLE events")

    # ---- re-parsing --------------------------------------------------------
    async def test_delete_for_evidence_enables_idempotent_reparse(self, store: EventStore) -> None:
        await store.insert_events([make_event(190), make_event(191, evidence_id="EVD-keep")])
        removed = await store.delete_for_evidence(TENANT, "EVD-contract")
        assert removed >= 1
        remaining = await store.search(EventQuery(tenant_id=TENANT))
        assert {e.evidence_id for e in remaining.events} == {"EVD-keep"}

    async def test_capabilities_are_declared(self, store: EventStore) -> None:
        capabilities = store.capabilities()
        assert capabilities.name == store.name
        assert isinstance(capabilities.fuzzy, bool)
        assert capabilities.notes
