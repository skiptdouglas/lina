"""OpenSearch search backend.

What OpenSearch adds over the event store: analyzed full-text over command
lines, fuzzy matching for typo-tolerant hunting, and relevance ranking. What it
does not add is authority — the index is derived data, rebuildable from the
event store, which is itself rebuildable from raw evidence. If the index and
the store ever disagree, the store wins.

Uses httpx directly rather than the ``opensearch-py`` client: the surface used
here is four REST calls, and one fewer dependency in a forensic tool is worth
more than the sugar.

**Unverified against a live cluster in this repository's CI.** The mapping and
queries below are written to the documented API; nothing here has been run
against a real OpenSearch node. Treat it as implemented-but-unproven until you
have exercised it — ``available()`` reports reachability so a deployment finds
out at startup rather than mid-investigation.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.events.mapping import event_to_row
from app.events.store import EventPage, EventQuery, StoreCapabilities
from app.normalization.schema import NormalizedEvent
from app.search.backend import SearchBackend

logger = logging.getLogger(__name__)

#: Analyzed for relevance; the rest are keyword fields for exact filtering.
INDEX_MAPPING: dict[str, Any] = {
    "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {
        "dynamic": False,
        "properties": {
            "event_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "case_id": {"type": "keyword"},
            "timestamp": {"type": "date"},
            "original_timestamp": {"type": "date"},
            "event_type": {"type": "keyword"},
            "category": {"type": "keyword"},
            "severity": {"type": "integer"},
            "user_name": {"type": "keyword"},
            "device_hostname": {"type": "keyword"},
            # keyword, not the ip type: forensic sources emit malformed and
            # placeholder addresses, and a strict ip field rejects the whole
            # document rather than the one bad value.
            "src_ip": {"type": "keyword"},
            "dst_ip": {"type": "keyword"},
            "dst_domain": {"type": "keyword"},
            "dst_port": {"type": "integer"},
            "process_name": {"type": "keyword"},
            "process_path": {"type": "text"},
            # The field most hunting actually targets.
            "process_command_line": {
                "type": "text",
                "fields": {"raw": {"type": "keyword", "ignore_above": 8192}},
            },
            "file_path": {
                "type": "text",
                "fields": {"raw": {"type": "keyword", "ignore_above": 4096}},
            },
            "file_sha256": {"type": "keyword"},
            "process_sha256": {"type": "keyword"},
            "evidence_id": {"type": "keyword"},
            "raw_reference": {"type": "keyword"},
            "document": {"type": "object", "enabled": False},
        },
    },
}

_FULL_TEXT_FIELDS = (
    "process_command_line^3",
    "process_path",
    "file_path",
    "process_name^2",
    "dst_domain^2",
    "device_hostname",
    "user_name",
    "event_type",
)


class OpenSearchBackend(SearchBackend):
    name = "opensearch"

    def __init__(
        self,
        *,
        url: str,
        index: str = "trace-events",
        username: str = "",
        password: str = "",
        verify_certs: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._index = index
        self._auth = (username, password) if username else None
        self._verify = verify_certs
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._url, auth=self._auth, verify=self._verify, timeout=self._timeout
        )

    async def ping(self) -> bool:
        try:
            async with self._client() as client:
                response = await client.get("/")
            return response.status_code == 200
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            logger.info("OpenSearch ping failed: %s", exc)
            return False

    async def available(self) -> tuple[bool, str]:
        if not self._url:
            return False, "TRACE_OPENSEARCH_URL is not set."
        if await self.ping():
            return True, f"Connected to {self._url}, index '{self._index}'."
        return False, f"OpenSearch at {self._url} is unreachable."

    def capabilities(self) -> StoreCapabilities:
        return StoreCapabilities(
            name=self.name,
            full_text=True,
            fuzzy=True,
            wildcard=True,
            regex=True,
            aggregation=True,
            notes=(
                "Analyzed full-text with fuzzy matching and relevance ranking. "
                "The index is derived data — rebuildable from the event store, "
                "which is rebuildable from raw evidence."
            ),
            extra={"index": self._index},
        )

    async def ensure_indices(self) -> None:
        async with self._client() as client:
            existing = await client.head(f"/{self._index}")
            if existing.status_code == 200:
                return
            created = await client.put(f"/{self._index}", json=INDEX_MAPPING)
            if created.status_code >= 400 and "resource_already_exists" not in created.text:
                raise RuntimeError(f"Could not create index {self._index}: {created.text}")

    async def index_events(self, events: list[NormalizedEvent]) -> int:
        if not events:
            return 0
        lines: list[str] = []
        for event in events:
            row = event_to_row(event)
            row.pop("extra", None)
            row["timestamp"] = event.timestamp.isoformat()
            row["original_timestamp"] = event.original_timestamp.isoformat()
            row["device_ip"] = list(event.device.ip or [])
            # The whole event travels along so a hit can be rendered without a
            # second round trip to the event store.
            row["document"] = event.model_dump(mode="json")
            # Indexing by event_id makes a re-parse overwrite rather than duplicate.
            lines.append(json.dumps({"index": {"_id": event.event_id}}))
            lines.append(json.dumps(row, default=str))
        body = "\n".join(lines) + "\n"

        async with self._client() as client:
            response = await client.post(
                f"/{self._index}/_bulk",
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenSearch bulk index failed: {response.text[:500]}")
        payload = response.json()
        if payload.get("errors"):
            failed = [
                item["index"].get("error")
                for item in payload.get("items", [])
                if item.get("index", {}).get("error")
            ]
            logger.error("OpenSearch rejected %d document(s): %s", len(failed), failed[:3])
            return len(events) - len(failed)
        return len(events)

    async def remove_evidence(self, tenant_id: str, evidence_id: str) -> int:
        async with self._client() as client:
            response = await client.post(
                f"/{self._index}/_delete_by_query",
                json={
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"tenant_id": tenant_id}},
                                {"term": {"evidence_id": evidence_id}},
                            ]
                        }
                    }
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenSearch delete-by-query failed: {response.text[:500]}")
        return int(response.json().get("deleted", 0))

    def _query_body(self, query: EventQuery) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [{"term": {"tenant_id": query.tenant_id}}]
        musts: list[dict[str, Any]] = []

        def term(field: str, value: Any) -> None:
            filters.append({"term": {field: value}})

        if query.case_id:
            term("case_id", query.case_id)
        if query.evidence_id:
            term("evidence_id", query.evidence_id)
        if query.event_types:
            filters.append({"terms": {"event_type": list(query.event_types)}})
        if query.categories:
            filters.append({"terms": {"category": list(query.categories)}})
        if query.min_severity is not None:
            filters.append({"range": {"severity": {"gte": query.min_severity}}})
        if query.time_from or query.time_to:
            bounds: dict[str, Any] = {}
            if query.time_from:
                bounds["gte"] = query.time_from.isoformat()
            if query.time_to:
                bounds["lte"] = query.time_to.isoformat()
            filters.append({"range": {"timestamp": bounds}})
        if query.user:
            term("user_name", query.user)
        if query.hostname:
            term("device_hostname", query.hostname)
        if query.domain:
            term("dst_domain", query.domain)
        if query.process:
            term("process_name", query.process)
        if query.ip:
            filters.append(
                {"bool": {"should": [
                    {"term": {"src_ip": query.ip}},
                    {"term": {"dst_ip": query.ip}},
                ], "minimum_should_match": 1}}
            )
        if query.file_hash:
            digest = query.file_hash.lower()
            filters.append(
                {"bool": {"should": [
                    {"term": {"file_sha256": digest}},
                    {"term": {"process_sha256": digest}},
                ], "minimum_should_match": 1}}
            )
        if query.entity:
            filters.append(
                {"bool": {"should": [
                    {"term": {field: query.entity}}
                    for field in ("user_name", "device_hostname", "process_name", "src_ip",
                                  "dst_ip", "dst_domain")
                ], "minimum_should_match": 1}}
            )
        if query.command_line:
            musts.append(
                {"match_phrase": {"process_command_line": query.command_line}}
            )
        if query.text:
            # Fuzziness is what OpenSearch is here for.
            musts.append(
                {
                    "multi_match": {
                        "query": query.text,
                        "fields": list(_FULL_TEXT_FIELDS),
                        "fuzziness": "AUTO",
                        "type": "best_fields",
                    }
                }
            )

        return {
            "query": {"bool": {"filter": filters, "must": musts or [{"match_all": {}}]}},
            "sort": [{"timestamp": {"order": "asc" if query.ascending else "desc"}}],
            "from": query.offset,
            "size": query.limit,
            "track_total_hits": True,
        }

    async def search(self, query: EventQuery) -> EventPage:
        started = time.monotonic()
        async with self._client() as client:
            response = await client.post(f"/{self._index}/_search", json=self._query_body(query))
        if response.status_code >= 400:
            raise RuntimeError(f"OpenSearch query failed: {response.text[:500]}")

        payload = response.json()
        hits = payload.get("hits", {})
        events = [
            NormalizedEvent.model_validate(hit["_source"]["document"])
            for hit in hits.get("hits", [])
            if hit.get("_source", {}).get("document")
        ]
        total = hits.get("total", {})
        return EventPage(
            events=events,
            total=int(total.get("value", len(events))) if isinstance(total, dict) else int(total),
            limit=query.limit,
            offset=query.offset,
            took_ms=int((time.monotonic() - started) * 1000),
            backend=self.name,
        )
