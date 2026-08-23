# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

TRACE — a forensic investigation platform. Backend: FastAPI + SQLAlchemy 2.0
async (Python 3.12+). Frontend: React + TypeScript + Vite. Storage: MinIO (raw
evidence), ClickHouse (event analytics), OpenSearch (search), Memgraph (graph),
Ollama (local LLM). Everything runs under Docker Compose.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before making structural
changes, and [docs/ROADMAP.md](docs/ROADMAP.md) to see which sprint owns a
feature. Sprint 1 (evidence foundation) is implemented; Sprints 2–7 are not.

## Commands

```bash
make init && make up      # start the stack (writes .env with generated secrets)
make test                 # backend tests — no infrastructure needed
make lint                 # ruff over backend/app and backend/tests
make frontend-build       # tsc + vite build
make demo-data            # synthetic telemetry for CASE-DEMO-001
```

There is no `yarn test` and no jest/vitest suite yet; the UI is verified by
`tsc -b && vite build` plus the backend contract tests.

## Rules that are not negotiable

1. **Never fabricate results.** An unimplemented capability raises
   `not_implemented("<capability.key>")` from `app.core.capabilities`, which
   returns HTTP 501. Add the capability to `CAPABILITIES` first — the registry
   is what `GET /api/v1/capabilities` and the UI read. No mock data in the
   product path; fixtures live in tests only (ADR-0004).
2. **Evidence is immutable.** Raw bytes are written once and never modified.
   Ingest hashes while streaming, writes to object storage, then re-reads and
   re-hashes the stored object before committing metadata. Parsers read a fresh
   copy from storage — never the upload stream (ADR-0005).
3. **Provenance is required, not optional.** Normalized events carry
   `evidence_id` + `raw_reference`; detections carry `event_ids`; graph edges
   carry the events that support them; an AI statement without an evidence
   reference cannot be a `FACT`. These are enforced in the models — do not
   loosen them.
4. **Audit before responding.** Sensitive actions write a hash-chained audit
   record in the same transaction as the action. Auditing is fail-closed.
   There is deliberately no API to update or delete an audit record.
5. **Tenant isolation.** `tenant_id` comes from the authenticated principal,
   never from the request body. A cross-tenant fetch returns 404, not 403.
6. **No credentials in source.** Secrets come from the environment. Compose
   declares them `${VAR:?...}` so a misconfigured deployment fails loudly.

## Conventions

* Layering is `api → service → repository/client`. A router never opens a
  database connection; a service never reads a `Request`.
* Python orchestrates, datastores compute. If a handler pulls more than ~10k
  rows into Python to produce a number, push it into ClickHouse SQL.
* External components sit behind ABCs (`ObjectStore`, `AnalyticsStore`,
  `GraphClient`, `AIProvider`, `AuditSink`, `SearchBackend`,
  `ThreatIntelProvider`). Business logic never imports a vendor SDK directly.
* New API routes need an explicit permission dependency —
  `Depends(require(PERMISSION))`. `tests/unit/test_auth_rbac.py` sweeps the
  OpenAPI schema and fails if a route is reachable unauthenticated.
* Record consequential decisions as a new ADR in `docs/adr/`; ADRs are
  immutable, a reversal supersedes.
* Run `make lint` and `make test` before committing.
