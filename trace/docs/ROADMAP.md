# TRACE — Roadmap

Build vertically: each sprint ends with something an investigator can
actually use, end to end, with tests.

**Definition of done** (§60 of the brief) — a feature is complete only when:
backend implemented · frontend implemented where applicable · persistent
storage works · authorization considered · audit trail created · error
handling implemented · tests pass · documentation updated · Docker deployment
works.

---

## Sprint 1 — Evidence foundation ✅ *implemented*

Repository · Docker Compose · FastAPI · React · ClickHouse · MinIO ·
Case management · Evidence upload · SHA-256.

Vertical slice proven by `tests/integration/test_sprint1_workflow.py`:

```
docker compose up → UI → create CASE-DEMO-001 → upload evidence
→ SHA-256 generated → raw object in MinIO → metadata stored
→ evidence listed in the case → Verify Evidence → hash recalculated → VERIFIED
```

Also delivered: hash-chained chain-of-custody audit, RBAC + tenant isolation,
`GET /capabilities`, the 501 NOT_IMPLEMENTED contract, ClickHouse schema
bootstrap, synthetic telemetry generator for `CASE-DEMO-001`.

### Sprint 1.5 — Evidence anchoring ✅ *implemented*

`docs/ANCHORING.md`. RFC 6962 transparency log (one leaf per evidence
manifest, appended in the ingest transaction), inclusion **and** consistency
proofs, Ed25519 signed tree heads, four anchor backends (local hash-chained
ledger, OpenTimestamps/Bitcoin, EVM, file receipt), proof bundles, and
`scripts/verify_anchor.py` — a dependency-free offline verifier a third party
can run without TRACE.

---

## Sprint 2 — Normalization, search, timeline ✅ *implemented*

[docs/NORMALIZATION.md](NORMALIZATION.md). Parser plugin framework with
registry and content sniffing; Sysmon (events 1, 3, 7, 10, 11, 13, 22),
Windows Security (incl. 1102 log clearing), Zeek (conn/dns/http/ssl/files),
Suricata EVE and generic Linux JSON; OCSF-inspired normalized events; a typed
`EventStore` with ClickHouse **and** SQL implementations held to one shared
contract suite ([ADR-0010](adr/0010-typed-event-store-interface.md)); a
byte-accurate `raw_reference` on every event with range-read retrieval of the
original record; `POST /api/v1/search` with capability reporting;
`GET /api/v1/cases/{id}/timeline`; clock-skew carried end to end; a failure-
isolating background parse worker; UI Search and Timeline with click-through to
the original bytes.

Deferred from this sprint, with reasons recorded rather than quietly dropped:
sandboxed parser containers (parsing is in-process with bounded limits), MinIO
object-lock (requires bucket creation with lock enabled — a deployment step,
documented), and native EVTX/PCAP readers (convert to JSON lines for now).

## Sprint 3 — Entities and graph

* Canonical entity registry + identity resolution (aliases never discarded)
* Memgraph client behind `GraphClient`; relationship writer requiring `event_ids`
* `GET /api/v1/entities`, `/entities/{id}`, `/graph/neighbourhood`
* UI: Entities, Graph explorer (expand / timeline / show evidence)

## Sprint 4 — Detections

* Sigma → ClickHouse SQL compilation, historical (retro-hunt) execution
* YARA / YARA-X scanning of stored evidence in an isolated worker
* MITRE ATT&CK tactic/technique/subtechnique on detection objects
* Rare-event and first-seen analytics (`/hunt/rare`, `/hunt/first-seen`)
* Basic cross-source correlation
* UI: Detections, MITRE coverage view

## Sprint 5 — Pattern Hunter and anomalies

* `POST /api/v1/patterns/find-similar` — event / sequence / process-tree /
  entity / case similarity, ranked
* Sequence matching from configuration (`rules/correlation/`)
* Behaviour baselines: user, host, service account (+ peer-group model)
* Explainable anomalies first: z-score, robust z-score, percentiles, moving
  averages, frequency deviation — every anomaly carries a `reason`
* Isolation Forest afterwards, never instead
* Beacon detection (interval, jitter, volume, confidence)
* Exfiltration heuristics
* UI: Pattern Hunter, Anomalies

## Sprint 6 — AI investigator

* `AIProvider` interface; Ollama implementation first
* AI Privacy Gateway (pseudonymise → strip → send → validate → re-attach)
* Retrieval-scoped context building — never send the datastore to the model
* `POST /api/v1/ai/investigate` returning
  `{summary, facts, inferences, hypotheses, unknowns, evidence, confidence}`
* FACT/INFERENCE/HYPOTHESIS/UNKNOWN guardrail enforced by the response
  validator: no evidence reference → cannot be a FACT
* UI: AI Investigator with evidence-linked answers

## Sprint 7 — Reporting, intel, privacy

* Evidence-backed report generation (all 15 sections of §42)
* Threat-intel providers: MISP, OpenCTI, STIX/TAXII (enrichment only)
* Pseudonymisation + `POST /api/v1/entities/{id}/reveal` (authorised, reasoned, audited)
* Evidence-gap detection (collector offline, missing ranges, log clearing, missing DNS)
* Contradiction detection → `EVIDENCE_CONFLICT`, never auto-resolved
* OIDC/SSO, investigation replay

---

## Backlog (tracked, not scheduled)

| Item | Note |
|---|---|
| `audit-distributed-chain` | DB-sequence or dedicated writer for multi-replica audit ordering (the transparency log append lock has the same constraint) |
| Persisted Merkle node cache | Roots are recomputed `O(n)` from leaves; fine to millions, not to billions |
| KMS/HSM log signing | `Signer` interface exists; `KmsSigner` raises rather than falling back |
| Bitcoin header validation | OTS attestation height is reported, not chain-validated |
| Signed collector receipts | Would move the anchored timestamp from ingest back to collection |
| Databricks / Delta Lake analytics backend | `AnalyticsStore` implementation alongside ClickHouse (§56) |
| Vector search in OpenSearch | semantic similarity for Pattern Hunter |
| Neo4j `GraphClient` | enterprise substitution |
| Natural-language investigation (§48) | builds on Sprints 5–6 |
| Investigation replay UI | audit stream already captures the inputs |
| Automatic peer grouping | data model exists in Sprint 5 |
