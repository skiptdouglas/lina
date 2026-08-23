# Sprint 1 — Implementation plan

**Goal:** a working vertical slice from `docker compose up` to
`VERIFIED`, with automated tests proving it.

```
docker compose up → TRACE starts → browser opens the UI
→ create CASE-DEMO-001 → upload evidence → SHA-256 generated
→ raw evidence stored in MinIO → metadata stored → evidence shown in the case
→ Verify Evidence → hash recalculated → VERIFIED
```

## Work breakdown

| # | Item | Files | Done when |
|---|---|---|---|
| 1 | Config & settings | `core/config.py` | All services configured by env, no defaults for secrets |
| 2 | Metadata DB | `core/db.py`, `*/models.py` | Async SQLAlchemy session, tables created at startup |
| 3 | AuthN/AuthZ | `core/security.py`, `api/deps.py` | Bearer tokens + dev mode; `require(perm)` dependency; tenant on principal |
| 4 | Errors & 501 contract | `core/errors.py`, `core/capabilities.py` | Uniform error body; `FeatureNotImplemented` → 501 |
| 5 | Object store | `evidence/storage.py` | `ObjectStore` ABC + MinIO + in-memory impls |
| 6 | Integrity | `evidence/integrity.py` | Streaming SHA-256, constant-memory, size counted |
| 7 | Audit chain | `audit/*` | Hash-chained records, sinks, verify-chain endpoint |
| 8 | Cases | `cases/*`, `api/v1/cases.py` | CRUD + sequential IDs + counts |
| 9 | Evidence ingest | `ingestion/service.py`, `api/v1/evidence.py` | Full §7 workflow incl. round-trip verification |
| 10 | Evidence verify | `evidence/service.py` | §8 response shape, audited, handles MISSING/MISMATCH |
| 11 | ClickHouse bootstrap | `core/clickhouse.py`, `deploy/clickhouse/*.sql` | Idempotent schema apply on startup, degraded-mode tolerant |
| 12 | Later-sprint stubs | `api/v1/*.py`, module ABCs | Every stub returns the 501 contract |
| 13 | Frontend | `frontend/src/**` | Cases, case detail, upload, verify, capabilities-driven placeholders |
| 14 | Compose | `docker-compose.yml`, Dockerfiles | Healthchecks + `depends_on: service_healthy` + volumes |
| 15 | Tests | `backend/tests/**` | Unit + integration incl. tamper detection |
| 16 | Demo data | `scripts/generate_demo_data.py` | Synthetic raw telemetry for CASE-DEMO-001 |

## Key decisions taken (see `docs/adr/`)

* Relational metadata store (SQLite → PostgreSQL by URL) — ADR-0003
* Round-trip verification on every ingest — ADR-0005
* Hash-chained audit, fail-closed — ADR-0006
* 501 instead of fake results — ADR-0004

## Explicitly out of scope for Sprint 1

Parsing, search, entities, graph, detections, patterns, anomalies, AI,
reports, threat intel, pseudonymisation. Each has an interface and a 501
stub; none returns fabricated data.

## Test plan

| Test | Proves |
|---|---|
| `unit/test_integrity.py` | streaming hash == `hashlib` over the same bytes, chunk-boundary safe |
| `unit/test_object_store.py` | put/stat/get/delete semantics of the ABC |
| `unit/test_audit_chain.py` | chain links, tamper detection, gap detection |
| `unit/test_auth_rbac.py` | anonymous 401, wrong-role 403, every route protected |
| `unit/test_not_implemented.py` | all stubs honour the 501 contract |
| `unit/test_cases_api.py` | create/list/get/patch, ID allocation, tenant isolation |
| `unit/test_evidence_api.py` | upload → hash → verify; MISMATCH on tamper; MISSING on delete |
| `integration/test_sprint1_workflow.py` | the whole §59 slice, audit trail included |
| `integration/test_minio_store.py` | real MinIO round trip (skipped when unavailable) |
