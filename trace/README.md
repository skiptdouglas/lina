# TRACE

**T**hreat **R**econstruction & **A**nalysis **C**orrelation **E**ngine — an
open-source forensic investigation platform.

> **AI output is analysis, not evidence.**
> Every conclusion TRACE presents can be walked back to an original,
> hash-verified artifact. A finding that cannot be traced to evidence is not
> presented as a forensic fact.

---

## Status: Sprints 1–2 of 7

TRACE is built vertically — each sprint ends with something an investigator can
use end to end. **Sprint 1 (evidence foundation) is implemented and tested.**

Working today:

* Docker Compose stack: API, UI, ClickHouse, OpenSearch, MinIO, Memgraph, Ollama
* Case management with human-readable identifiers (`CASE-0042`, `CASE-DEMO-001`)
* Evidence ingest — streamed, SHA-256 hashed, stored raw in MinIO, and
  **round-trip verified before the metadata row is committed**
* Integrity verification on demand, including tamper and missing-object detection
* Hash-chained chain of custody with an integrity check of its own
* **Normalization** — parsers for Sysmon, Windows Security, Zeek, Suricata and
  Linux JSON, producing OCSF-inspired events that each address the exact bytes
  they came from ([docs/NORMALIZATION.md](docs/NORMALIZATION.md))
* **Search and timeline** — query across every parsed source, reconstruct a case
  chronologically, and click any event through to its original record
* **Evidence anchoring** — an RFC 6962 Merkle log of evidence manifests, signed
  tree heads, and roots published to an immutable ledger
  ([docs/ANCHORING.md](docs/ANCHORING.md))
* RBAC, tenant isolation, rate limiting, audited downloads
* `GET /api/v1/capabilities` — a machine-readable map of what is and is not built

Not built yet: entities, graph, detections, Pattern Hunter, anomalies, AI
investigation, reporting, threat intel, pseudonymisation. Those endpoints
return **HTTP 501 `NOT_IMPLEMENTED`** — never fabricated results
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
6. Press **Parse** on the evidence row, then **Timeline** to see the incident
   reconstructed — click any event to read the original source record
7. Open **Anchoring → Anchor now**, then use **Show proof** on the evidence row
   to walk file → digest → manifest → leaf → root → signature → ledger

The API is at http://localhost:8000, with interactive docs at `/docs`.

To drive the same workflow from a shell:

```bash
make demo-data
TRACE_TOKEN=<your token> ./scripts/smoke.sh
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
Finding → Detection → Normalized Event → Original Record → Evidence Object → SHA-256
                          raw_reference ─┘                                      ↓
                                          Merkle leaf → signed root → immutable ledger
```

`raw_reference` is a byte-accurate locator (`jsonl:12:4096:312`), so
`GET /evidence/{id}/record` range-reads the exact source record out of a stored
artifact — one record from a 40 GB image without downloading the image.

This is structural, not a convention: detections require the event IDs they
fired on, graph edges require the events that support them, and an AI statement
with no evidence reference cannot be serialized as a `FACT`.

### Evidence anchoring

```
Evidence File → SHA-256 → Manifest → Merkle Leaf → Root → Signed by TRACE → Ledger
```

**Only the 32-byte root reaches the ledger.** Evidence, manifests and case
metadata never leave TRACE — publishing them would expose live investigations
permanently and collide head-on with the right to erasure
([ADR-0007](docs/adr/0007-anchor-merkle-roots-not-evidence.md)).

Backends: a local hash-chained ledger (self-attested, works offline),
OpenTimestamps (Bitcoin, free, confirms in hours), an EVM chain (costs gas,
confirms in minutes), or a signed file receipt for an external notary. Each
anchor records how independent it is, and TRACE never lets a local anchor be
mistaken for a blockchain one.

Any evidence object yields a **proof bundle** that verifies with no access to
TRACE at all:

```bash
python3 scripts/verify_anchor.py proof.json \
    --evidence-file sysmon.jsonl --expect-key-id <published key id>
```

That script has no dependencies — standard library only, with a pure-Python
Ed25519 verifier built in — so it runs on an air-gapped laptop. A guarantee you
can only check by asking the system under scrutiny is not a guarantee.

**What an anchor proves:** this digest existed before a given time, and the log
was not rewritten. **What it does not prove:** that the evidence is authentic.
Anchoring a forgery anchors a forgery. TRACE says so in the API response, the
bundle, the UI and the verifier output.

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, layering, replaceable interfaces, provenance |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Cases, evidence, audit chain, events, entities, graph |
| [docs/API.md](docs/API.md) | Endpoints, the 501 contract, request/response shapes |
| [docs/NORMALIZATION.md](docs/NORMALIZATION.md) | Parsers, event storage, search, timeline, clock skew, limits |
| [docs/ANCHORING.md](docs/ANCHORING.md) | Merkle log, signing, ledgers, proof bundles, threat model, known limits |
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
scripts/     Environment init, signing-key generation, synthetic telemetry,
             smoke test, and the dependency-free offline proof verifier
sample-data/ Generated synthetic telemetry (git-ignored)
docs/        Architecture, data model, API, security, roadmap, ADRs
```

---

## Development

```bash
make backend-deps      # create backend/.venv
make test              # 353 tests, no infrastructure required
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

Sprint 2 adds: parsers exercised against the same synthetic telemetry an
analyst would upload, byte-locator round-trips across awkward chunk boundaries,
a shared event-store contract suite run against both backends, the
lossless column/`extra` mapping asserted field by field, worker
failure-isolation, and a full slice from four raw artifacts to one reconstructed
timeline and back to the original bytes.

Anchoring adds: the RFC 6962 tree checked exhaustively against an independent
verifier (every leaf of every tree size to 33, every consistency pair — around
1,100 cases), regression tests for both classic Merkle flaws, the manifest
mutability contract in both directions, a pure-Python Ed25519 implementation
cross-checked against `cryptography`, and the offline verifier run as a real
subprocess — including with `cryptography` deliberately blocked.

---

## Security

TRACE holds the most sensitive telemetry an organisation has. Security is part
of the architecture, not a later sprint — see
[docs/SECURITY.md](docs/SECURITY.md) for the threat model, the permission
matrix, evidence-handling rules, the AI boundary, and an explicit list of
**known gaps in the MVP**.

There are no credentials in this repository. Compose refuses to start when a
secret is missing rather than falling back to a default password. The Ed25519
log signing key is generated by `make init` into `deploy/keys/` (git-ignored)
and mounted read-only; TRACE refuses to generate an ephemeral one in
staging or production.

Report vulnerabilities privately to the maintainers rather than in a public
issue.

---

## Licence

Apache-2.0 — see [LICENSE](LICENSE).
