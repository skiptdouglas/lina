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

---

## Sprint 2 — Normalization, search, timeline

* Parser plugin framework (`normalization/parsers/`), registry + dispatch
* Sysmon: events 1, 3, 7, 10, 11, 13, 22
* Windows Security events, Linux JSON, Zeek JSON, Suricata EVE JSON
* OCSF-inspired normalized event → ClickHouse `trace.events`
* `raw_reference` byte/record locator for every event (provenance)
* OpenSearch indexing + `POST /api/v1/search`
* `GET /api/v1/cases/{case_id}/timeline`
* Clock-skew fields carried end to end
* Sandboxed parse workers; MinIO object-lock/versioning enabled
* UI: Search, Timeline (interactive, click-through to evidence)

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
| `audit-distributed-chain` | DB-sequence or dedicated writer for multi-replica audit ordering |
| Databricks / Delta Lake analytics backend | `AnalyticsStore` implementation alongside ClickHouse (§56) |
| Vector search in OpenSearch | semantic similarity for Pattern Hunter |
| Neo4j `GraphClient` | enterprise substitution |
| Natural-language investigation (§48) | builds on Sprints 5–6 |
| Investigation replay UI | audit stream already captures the inputs |
| Automatic peer grouping | data model exists in Sprint 5 |
