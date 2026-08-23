# TRACE — Architecture

**T**hreat **R**econstruction & **A**nalysis **C**orrelation **E**ngine

> **Fundamental rule:** AI output is *analysis*, not *evidence*.
> Every conclusion presented by TRACE must be traceable to an original,
> hash-verified evidence object.

---

## 1. System overview

```
Collectors (sysmon / windows / linux / zeek / suricata)
    │
    ▼
Ingestion API  ────────────────────────► MinIO  (RAW EVIDENCE, immutable)
    │                                      ▲
    ▼                                      │ sha256 verified round-trip
Normalization (parser plugins)             │
    │                                      │
    ▼                                      │
ClickHouse (normalized events) ────────────┘  raw_reference / evidence_id
    │
    ├────► OpenSearch  (full-text, fuzzy, future vector)
    │
    └────► Memgraph    (entities & relationships)
               │
               ▼
        Correlation Engine
               │
       ┌───────┼─────────┐
       ▼       ▼         ▼
     Sigma   Pattern   Anomaly
             Hunter    Engine
       │       │         │
       └───────┼─────────┘
               ▼
        AI Privacy Gateway ──► AI Investigator
               │
               ▼
           TRACE API (FastAPI)
               │
               ▼
          React Web UI
```

### Data-flow invariants

1. **Raw before parsed.** Evidence is written to object storage and
   round-trip verified *before* any parser touches it. TRACE never parses the
   only copy of an artifact.
2. **Append-only analytics.** Normalized events in ClickHouse are derived
   data. They can be rebuilt from raw evidence at any time; raw evidence can
   never be rebuilt from them.
3. **Every derived record carries provenance.** A normalized event stores
   `evidence_id` + `raw_reference` (byte offset / record index inside the
   original object). A detection stores the event IDs it fired on. A finding
   stores the detections. A report stores the findings.
4. **Audit is a first-class store, not a log file.** Audit records are
   hash-chained so that removal or modification of a record is detectable.

---

## 2. Component responsibilities

| Component | Responsibility | Replaceable with |
|---|---|---|
| `trace-api` | Orchestration, authorization, provenance. Not the analytics engine. | — |
| `trace-ui` | Analyst interface. Never talks to an LLM or a datastore directly. | — |
| MinIO | Immutable raw evidence objects | AWS S3, Ceph RGW (S3 API) |
| ClickHouse | Primary event analytics (aggregation, time-series, rarity) | Databricks + Delta Lake |
| OpenSearch | Full-text / command-line / fuzzy / future vector search | Elasticsearch |
| Memgraph | Entity + relationship graph, path queries | Neo4j (Bolt/Cypher) |
| Ollama | Local LLM inference | OpenAI, Azure OpenAI, Anthropic, vLLM |
| Metadata DB | Cases, evidence metadata, audit chain, entity registry | SQLite (dev) → PostgreSQL (prod) |

Every external component sits behind an interface in `backend/app/core` or
its owning module (see §5). No business logic imports a vendor SDK directly.

---

## 3. Performance philosophy

Python **orchestrates**; it does not compute.

* Aggregations, rarity counts, first-seen/last-seen, histogram and
  percentile maths → **ClickHouse SQL**.
* Text / fuzzy / wildcard matching → **OpenSearch queries**.
* Path finding, neighbourhood expansion, subgraph extraction → **Cypher in
  Memgraph**.
* Python does: request validation, authorization, provenance stitching,
  orchestration, and result shaping.

A rule of thumb enforced in review: *if a handler pulls more than ~10k rows
into Python to compute a number, the computation belongs in the datastore.*

---

## 4. Backend layout

```
backend/app/
├── main.py            FastAPI application factory + lifespan
├── api/               HTTP layer only — no business logic
│   ├── deps.py        auth / principal / service dependencies
│   └── v1/            versioned routers (one module per resource)
├── core/              config, security, db, clickhouse, ids, errors
├── ingestion/         upload intake, parse queue
├── evidence/          evidence model, object storage, integrity
├── normalization/     OCSF-inspired event schema + parser plugin registry
├── entities/          canonical entities + identity resolution
├── graph/             graph client abstraction (Memgraph today)
├── detections/        Sigma + YARA engines, MITRE ATT&CK mapping
├── correlation/       cross-source correlation, sequences, contradictions
├── patterns/          Pattern Hunter (similarity search)
├── anomalies/         baselines, statistical anomalies, beaconing
├── timeline/          timeline assembly, clock-skew model
├── threatintel/       MISP / OpenCTI / STIX-TAXII providers
├── ai/                provider abstraction + privacy gateway + investigator
├── cases/             case management
├── reports/           evidence-backed report generation
├── privacy/           pseudonymisation + identity reveal
└── audit/             chain-of-custody records (hash-chained)
```

**Layering rule:** `api → service → repository/client`. A router never opens
a database connection; a service never reads a `Request`.

---

## 5. Interfaces designed for replacement

Defined as abstract base classes, selected by configuration:

| Interface | Location | Implementations |
|---|---|---|
| `ObjectStore` | `evidence/storage.py` | `MinioObjectStore`, `InMemoryObjectStore` (tests) |
| `AnalyticsStore` | `core/analytics.py` | `ClickHouseAnalyticsStore`, *Databricks (planned)* |
| `SearchBackend` | `core/search_backend.py` | *OpenSearch (Sprint 2)* |
| `GraphClient` | `graph/client.py` | *Memgraph (Sprint 3)*, *Neo4j (planned)* |
| `AIProvider` | `ai/provider.py` | *Ollama (Sprint 6)*, OpenAI/Azure/Anthropic/vLLM (planned) |
| `AuditSink` | `audit/sinks.py` | `SqlAuditSink`, `ClickHouseAuditSink`, `NullAuditSink` |
| `AnchorBackend` | `anchoring/backends/` | `LocalLedger`, `OpenTimestamps`, `Evm`, `FileReceipt` |
| `Signer` | `anchoring/signing.py` | `Ed25519Signer`, *KMS/HSM (planned)* |
| `IngestionQueue` | `ingestion/queue.py` | `InMemoryIngestionQueue`, *broker-backed (planned)* |
| `ThreatIntelProvider` | `threatintel/provider.py` | *MISP / OpenCTI / TAXII (Sprint 7)* |

Unimplemented interfaces exist as ABCs with documented method contracts and
**raise `FeatureNotImplemented` (HTTP 501)** rather than returning plausible
but fabricated data. See §9.

---

## 6. Storage model — which store owns what

| Data | Store | Why |
|---|---|---|
| Raw evidence bytes | MinIO | Immutable, content-addressed by SHA-256, versioned |
| Evidence metadata | Metadata DB | Mutable-ish (legal hold, retention), relational, transactional |
| Cases | Metadata DB | Small, transactional, frequently updated |
| Audit / chain of custody | Metadata DB (chain of record) + ClickHouse (append-only mirror) | Chain integrity needs ordered writes; ClickHouse gives cheap long-term retention and fast querying |
| Normalized events | ClickHouse | Billions of rows, columnar aggregation |
| Search index | OpenSearch | Text analysis TRACE should not reimplement |
| Entities & relationships | Memgraph (+ registry in Metadata DB) | Traversal, path queries |
| Pseudonym mappings | Metadata DB, **separate table + separate access control** | Must be isolatable from analytics data (§30) |
| Transparency log leaves | Metadata DB (`merkle_leaves`) | Append-only; written in the same transaction as the evidence row |
| Anchors / signed tree heads | Metadata DB (`anchors`) + an external ledger | The ledger holds only a 32-byte root (ADR-0007) |

> **ADR-0003** explains why case/evidence metadata is *not* in ClickHouse:
> ClickHouse is not designed for high-frequency small mutations
> (legal hold flips, case status changes) or for transactional integrity.

---

## 6a. Evidence anchoring

Ingest appends the evidence *manifest* to a per-tenant RFC 6962 transparency
log. Periodically the root of that log is signed (Ed25519) and published to an
immutable ledger:

```
Evidence -> SHA-256 -> Manifest -> Merkle leaf -> Root -> Signed -> Ledger
```

**Only the 32-byte root leaves TRACE.** Evidence, manifests and case metadata
never reach a ledger — see [ADR-0007](adr/0007-anchor-merkle-roots-not-evidence.md).
Backends differ in how independent they are (`local` is self-attested;
OpenTimestamps and EVM are not), and that difference is reported everywhere
rather than blurred ([ADR-0009](adr/0009-anchoring-claims-must-be-precise.md)).

Proof bundles are verifiable offline by `scripts/verify_anchor.py`, which has
no dependencies and no TRACE imports — a guarantee only checkable by the
system under scrutiny is not a guarantee. Full design in
[ANCHORING.md](ANCHORING.md).

## 7. Provenance chain (the "SHOW EVIDENCE" requirement)

Every UI surface that presents a conclusion must be able to walk:

```
Finding            findings.detection_ids[]
   ↓
Detection          detections.event_ids[]
   ↓
Normalized Event   events.evidence_id + events.raw_reference
   ↓
Original Event     byte range / record index inside the raw object
   ↓
Evidence Object    evidence.storage_bucket + storage_key
   ↓
SHA-256            evidence.sha256  → GET /evidence/{id}/verify
   ↓
Merkle leaf        SHA-256(0x00 || canonical manifest)
   ↓
Signed root        Ed25519 tree head → published to a ledger
```

The last two steps are what let the chain be checked by someone who does not
trust TRACE: `GET /evidence/{id}/proof` returns a self-contained bundle.

This is enforced structurally: the report and finding models **require**
non-empty provenance references. A statement with no evidence reference
cannot be serialized as a `FACT` (see `ai/schemas.py`, §36).

---

## 8. Security architecture

Summarised here, detailed in [SECURITY.md](SECURITY.md).

* **AuthN** — pluggable. MVP: bearer tokens from secret storage. Planned: OIDC.
* **AuthZ** — role → permission matrix, enforced by FastAPI dependencies.
* **Tenant isolation** — every first-class row carries `tenant_id`; repository
  helpers refuse unscoped queries.
* **Audit** — sensitive actions are recorded *before* the response is returned;
  audit failure fails the request closed (configurable).
* **Secrets** — read from the environment/secret store only. The repository
  contains no credentials; `docker-compose.yml` requires secrets to be set
  and fails loudly when they are absent.
* **AI boundary** — the browser can never reach an LLM. All model traffic
  crosses the AI Privacy Gateway server-side.

---

## 9. "NOT IMPLEMENTED" contract

TRACE is built vertically over seven sprints. Anything not yet built:

* returns **HTTP 501** with body
  `{"status": "NOT_IMPLEMENTED", "feature": "...", "planned_sprint": N, "detail": "..."}`
* is listed by `GET /api/v1/capabilities`
* is rendered by the UI as an explicit **NOT IMPLEMENTED** panel

TRACE never returns invented scores, fabricated similarity results, or
placeholder findings. A forensic tool that lies about its own coverage is
worse than one with gaps.

---

## 10. Deployment

`docker compose up` starts the full stack; every stateful service has a named
volume and a health check, and `trace-api` waits for its dependencies to
report healthy. See [../README.md](../README.md) and
[ROADMAP.md](ROADMAP.md) for the sprint-by-sprint scope.
