# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

TRACE — a forensic investigation platform. Backend: FastAPI + SQLAlchemy 2.0
async (Python 3.12+). Frontend: React + TypeScript + Vite. Storage: MinIO (raw
evidence), ClickHouse (event analytics), OpenSearch (search), Memgraph (graph),
Ollama (local LLM). Everything runs under Docker Compose.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before making structural
changes, and [docs/ROADMAP.md](docs/ROADMAP.md) to see which sprint owns a
feature. Sprints 1–2 (evidence foundation, anchoring, normalization/search/
timeline) are implemented; Sprints 3–7 are not.

## Commands

```bash
make init && make up      # start the stack (writes .env with generated secrets)
make test                 # backend tests — no infrastructure needed
make lint                 # ruff over backend/app and backend/tests
make frontend-build       # tsc + vite build
make demo-data            # synthetic telemetry for CASE-DEMO-001
make signing-key          # Ed25519 key for signing Merkle tree heads
make verify-proof BUNDLE=proof.json FILE=evidence.log KEY_ID=<id>
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
7. **Only a Merkle root is ever anchored.** `AnchorBackend.submit` takes
   `(root_hash, sth)` and nothing else. Never widen that signature — evidence,
   manifests, case ids and filenames must never reach a ledger (ADR-0007).
8. **Never overstate what an anchor proves.** Every anchor carries its
   `independence`; a `local` anchor is self-attested, not blockchain-backed.
   Proof bundles and the offline verifier always print
   `what_this_does_not_prove`. Marketing language here is a review defect
   (ADR-0009).
9. **Every event carries provenance.** `evidence_id` plus a byte-accurate
   `raw_reference`. A parser that cannot locate a record's bytes must not emit
   an event for it. Never widen a record locator into a general read: it is
   validated, bounded by the object size, and size-capped.
10. **Never overwrite an original timestamp.** Clock corrections are recorded
   beside the original with a method and a confidence, never in place of it.
11. **Absence is not zero** (ADR-0011). PID 0 is a real process; an empty file
   has size 0. New numeric columns must answer explicitly whether zero is a
   real value, and be nullable if it is.
12. **Report what a parse did NOT do.** Unrecognised record types, skipped
   malformed lines and truncation are counted and surfaced. An analyst
   concluding "that did not happen" needs to know whether TRACE looked.
13. **Manifests commit immutable fields only.** Adding a mutable field to
   `COMMITTED_EVIDENCE_FIELDS` would invalidate every previously issued proof
   the first time it changed. `tests/unit/test_manifest.py` guards both
   directions.

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
* `scripts/verify_anchor.py` and `scripts/generate_signing_key.py` are
  standalone: no TRACE imports, no third-party dependencies, standard library
  only. They must stay that way — a third party has to be able to run them on
  an air-gapped machine. If you change canonical serialization, the Merkle
  construction or the signature domain, update the verifier in lockstep;
  `tests/integration/test_offline_verifier.py` runs it as a real subprocess.
* The event store interface takes typed queries, not SQL (ADR-0010). If a new
  query shape is needed, add a method — every backend must be able to serve it,
  and `tests/contract/event_store_contract.py` runs against all of them.
* Record consequential decisions as a new ADR in `docs/adr/`; ADRs are
  immutable, a reversal supersedes.
* Run `make lint` and `make test` before committing.
