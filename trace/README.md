# TRACE

**T**hreat **R**econstruction & **A**nalysis **C**orrelation **E**ngine — an
open-source forensic investigation platform.

> **AI output is analysis, not evidence.**
> Every conclusion TRACE presents can be walked back to an original,
> hash-verified artifact. A finding that cannot be traced to evidence is not
> presented as a forensic fact.

---

## Status: Sprint 1 of 7

TRACE is built vertically — each sprint ends with something an investigator can
use end to end. **Sprint 1 (evidence foundation) is implemented and tested.**

Working today:

* Docker Compose stack: API, UI, ClickHouse, OpenSearch, MinIO, Memgraph, Ollama
* Case management with human-readable identifiers (`CASE-0042`, `CASE-DEMO-001`)
* Evidence ingest — streamed, SHA-256 hashed, stored raw in MinIO, and
  **round-trip verified before the metadata row is committed**
* Integrity verification on demand, including tamper and missing-object detection
* Hash-chained chain of custody with an integrity check of its own
* RBAC, tenant isolation, rate limiting, audited downloads
* `GET /api/v1/capabilities` — a machine-readable map of what is and is not built

Not built yet: parsing, search, entities, graph, detections, Pattern Hunter,
anomalies, AI investigation, reporting, threat intel, pseudonymisation. Those
endpoints return **HTTP 501 `NOT_IMPLEMENTED`** — never fabricated results
([ADR-0004](docs/adr/0004-not-implemented-over-fake-results.md)).
See [docs/ROADMAP.md](docs/ROADMAP.md) for what lands when.

---

## Quick start

Requirements: Docker with Compose v2, ~6 GB of RAM free (OpenSearch and Ollama
are the hungry ones), Python 3.12+ and Node 22+ if you want to run the tests.

```bash
make init      # writes .env with generated local secrets, prints your API token
make up        # builds and starts the stack, waiting for health checks
```

Then open **http://localhost:3000**, paste the token from `make init` into the
field at the top right, and:

1. **Cases → + New case** — create `CASE-DEMO-001`
2. **Add evidence** — drop in a log or use `make demo-data` for synthetic telemetry
3. Watch the SHA-256 appear, computed over the bytes TRACE actually received
4. Press **Verify evidence** — the stored object is re-read, re-hashed, and
   reported as `VERIFIED`
5. Scroll to **Chain of custody** to see `CASE_CREATE → COLLECT → STORE → VERIFY`

The API is at http://localhost:8000, with interactive docs at `/docs`.

To drive the same workflow from a shell:

```bash
make demo-data
TRACE_TOKEN=<your token> ./scripts/smoke_sprint1.sh
```

---

## Architecture

```
Collectors ──► Ingestion API ──► MinIO (raw evidence, immutable)
                     │
                     ▼
              Normalization ──► ClickHouse ──┬──► OpenSearch
                                             └──► Memgraph
                                                     │
                                      Correlation ◄──┘
                                  ┌──────┼──────┐
                                Sigma  Pattern  Anomaly
                                       Hunter   Engine
                                  └──────┼──────┘
                                         ▼
                            AI Privacy Gateway ──► AI Investigator
                                         ▼
                                    TRACE API ──► React UI
```

Python **orchestrates**; it does not compute. Aggregation belongs in ClickHouse,
text matching in OpenSearch, traversal in Memgraph
([docs/ARCHITECTURE.md §3](docs/ARCHITECTURE.md)).

Every external component sits behind an interface, so MinIO→S3,
ClickHouse→Databricks, Memgraph→Neo4j, Ollama→OpenAI and OpenSearch→Elastic are
configuration changes rather than rewrites.

### The provenance chain

```
Finding → Detection → Normalized Event → Original Event → Evidence Object → SHA-256
```

This is structural, not a convention: detections require the event IDs they
fired on, graph edges require the events that support them, and an AI statement
with no evidence reference cannot be serialized as a `FACT`.

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, layering, replaceable interfaces, provenance |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Cases, evidence, audit chain, events, entities, graph |
| [docs/API.md](docs/API.md) | Endpoints, the 501 contract, request/response shapes |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, RBAC matrix, evidence handling, AI boundary, known gaps |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Sprint-by-sprint scope and definition of done |
| [docs/SPRINT1_PLAN.md](docs/SPRINT1_PLAN.md) | The plan this sprint was built against |
| [docs/adr/](docs/adr/) | Architecture decisions and why they were made |

---

## Repository layout

```
backend/     FastAPI service — api, core, ingestion, evidence, normalization,
             correlation, patterns, anomalies, entities, graph, detections,
             timeline, threatintel, ai, cases, reports, privacy, audit
frontend/    React + TypeScript + Vite analyst UI
collectors/  Collection contracts and configuration per source
rules/       sigma/ · yara/ · correlation/ (sequence definitions)
schemas/     OCSF-inspired event schema and mapping
deploy/      ClickHouse DDL applied at startup
scripts/     Environment init, synthetic telemetry, smoke test
sample-data/ Generated synthetic telemetry (git-ignored)
docs/        Architecture, data model, API, security, roadmap, ADRs
```

---

## Development

```bash
make backend-deps      # create backend/.venv
make test              # 88 tests, no infrastructure required
make lint              # ruff over app and tests
make frontend-deps
make frontend-build    # typecheck + production build

# tests that need live MinIO
TRACE_MINIO_ENDPOINT=localhost:9000 \
TRACE_MINIO_ACCESS_KEY=... TRACE_MINIO_SECRET_KEY=... make test-integration
```

The suite covers streaming-hash correctness, path-traversal resistance, the
full ingest→verify workflow, tamper and missing-object detection, audit-chain
tamper detection, the RBAC matrix (including a sweep asserting every `/api/v1`
route is authenticated), and the 501 contract for every stub.

---

## Security

TRACE holds the most sensitive telemetry an organisation has. Security is part
of the architecture, not a later sprint — see
[docs/SECURITY.md](docs/SECURITY.md) for the threat model, the permission
matrix, evidence-handling rules, the AI boundary, and an explicit list of
**known gaps in the MVP**.

There are no credentials in this repository. Compose refuses to start when a
secret is missing rather than falling back to a default password.

Report vulnerabilities privately to the maintainers rather than in a public
issue.

---

## Licence

Apache-2.0 — see [LICENSE](LICENSE).
