# TRACE — API

Base path `/api/v1`. All responses JSON. All timestamps RFC 3339 UTC.

Authentication: `Authorization: Bearer <token>` (see [SECURITY.md](SECURITY.md)).
In `TRACE_AUTH_MODE=dev` a development principal is injected and every request
is logged with a loud warning — dev mode refuses to start when `TRACE_ENV=prod`.

## Status conventions

| Code | Meaning |
|---|---|
| 400 | Validation error |
| 401 | Missing/invalid credentials |
| 403 | Authenticated but lacking permission (or crossing a tenant boundary) |
| 404 | Not found *or* not visible to this tenant |
| 409 | Conflict (duplicate case id, legal hold violation) |
| 413 | Upload exceeds `TRACE_EVIDENCE_MAX_UPLOAD_BYTES` |
| 422 | Semantic error |
| 429 | Rate limited |
| **501** | **Feature not implemented yet — see below** |

### The 501 contract

```json
{
  "status": "NOT_IMPLEMENTED",
  "feature": "patterns.find_similar",
  "planned_sprint": 5,
  "detail": "Pattern Hunter similarity search is not implemented.",
  "reference": "docs/ROADMAP.md#sprint-5"
}
```

TRACE never returns fabricated results for unimplemented features.
`GET /api/v1/capabilities` enumerates what is and is not implemented.

---

## Implemented — Sprint 1

### Health
```
GET  /health                 liveness, no auth
GET  /api/v1/health/ready    per-dependency readiness (db, object store, clickhouse)
GET  /api/v1/capabilities    implemented/not-implemented map
```

### Cases
```
POST   /api/v1/cases         create            perm case:create
GET    /api/v1/cases         list + filter     perm case:read
GET    /api/v1/cases/{id}    detail + counts   perm case:read
PATCH  /api/v1/cases/{id}    partial update    perm case:update
```

`POST /api/v1/cases`
```json
{ "title": "Suspected phishing → lateral movement",
  "description": "...", "severity": "HIGH",
  "investigator": "a.analyst", "case_id": "CASE-DEMO-001", "tags": ["demo"] }
```
`case_id` is optional; when omitted TRACE allocates the next `CASE-NNNN`.

### Evidence
```
POST /api/v1/evidence                     multipart upload      perm evidence:create
GET  /api/v1/evidence?case_id=...         list                  perm evidence:read
GET  /api/v1/evidence/{id}                metadata              perm evidence:read
GET  /api/v1/evidence/{id}/verify         integrity check       perm evidence:verify
GET  /api/v1/evidence/{id}/download       raw bytes             perm evidence:download
```

**Upload** (`multipart/form-data`)

| Part | Required | Notes |
|---|---|---|
| `file` | yes | the artifact |
| `case_id` | yes | must exist and be visible to the tenant |
| `source` | yes | host/system the artifact came from |
| `source_type` | no | default `OTHER` |
| `collector` | no | default `manual-upload/1.0` |
| `acquisition_method` | no | default `MANUAL_UPLOAD` |
| `original_path`, `original_timestamp`, `collection_timestamp`, `retention_policy`, `legal_hold`, `notes` | no | |

Ingest workflow (`ingestion/service.py`):

```
Upload → spool to disk (streamed, hashed)   ← never buffered wholly in memory
       → generate evidence_id
       → SHA-256 of the received bytes
       → PUT raw object to MinIO
       → re-read the stored object and re-hash  (round-trip verification)
       → persist metadata
       → audit COLLECT + STORE + VERIFY
       → queue parsing (parse_status=QUEUED)
```
If round-trip verification fails, the object is removed and the upload is
rejected with 500 — TRACE will not register evidence it cannot prove it stored.

**Verify** `GET /api/v1/evidence/{id}/verify`
```json
{ "verified": true, "expected_hash": "e3b0c…", "actual_hash": "e3b0c…",
  "evidence_id": "EVD-…", "algorithm": "sha256",
  "size_expected": 4096, "size_actual": 4096, "result": "VERIFIED",
  "verified_at": "2026-08-23T10:00:00Z" }
```
`result` ∈ `VERIFIED` · `MISMATCH` · `MISSING` · `ERROR`. Verification always
writes an audit record, including when it fails.

### Audit / chain of custody
```
GET /api/v1/audit                    filter by case/evidence/action/actor   perm audit:read
GET /api/v1/audit/verify-chain       recompute the hash chain              perm audit:read
```

### Normalization, search and timeline

Design in [NORMALIZATION.md](NORMALIZATION.md).

```
GET  /api/v1/ingestion/parsers                which formats and record types   perm evidence:create
POST /api/v1/ingestion/parse/{evidence_id}    parse stored evidence            perm evidence:create
POST /api/v1/search                           search normalized events         perm search:query
GET  /api/v1/events/{event_id}                one event                        perm search:query
GET  /api/v1/cases/{case_id}/timeline         chronological reconstruction     perm case:read
GET  /api/v1/evidence/{id}/record?reference=  the original bytes of a record   perm evidence:read
```

`POST /api/v1/ingestion/parse/{id}` reports what it did **and did not** do:

```json
{ "parse_status": "PARSED", "parser_id": "sysmon-json",
  "events_produced": 13, "records_read": 13, "records_skipped": 0,
  "unrecognised": 4, "unrecognised_types": {"EventID 15": 4},
  "truncated": false, "errors": [], "detail": "…" }
```

Re-parsing needs `{"force": true}` and **replaces** the artifact's events rather
than appending, so a corrected clock offset cannot double a timeline.

`POST /api/v1/search` always reports which backend answered and what it can
express, so "no results" is never ambiguous:

```json
{ "events": [...], "total": 3, "took_ms": 4,
  "backend": {"name": "sql", "fuzzy": false, "full_text": true,
              "notes": "Substring matching over indexed columns. No fuzzy…"} }
```

`GET /api/v1/cases/{id}/timeline` returns entries carrying both timestamps, a
`clock_corrected` flag, and a `provenance` block linking to the original record.

`GET /api/v1/evidence/{id}/record?reference=jsonl:12:4096:312` range-reads the
stored object and returns exactly those bytes — the last hop of the "SHOW
EVIDENCE" chain. The locator is validated, bounded by the object size, and
capped by `TRACE_RECORD_MAX_BYTES`; it is a provenance pointer, not a read
primitive.

### Evidence anchoring

Full design in [ANCHORING.md](ANCHORING.md). Only a 32-byte Merkle root ever
reaches a ledger (ADR-0007).

```
GET  /api/v1/anchoring/log                    size, root, last anchor, public key   perm anchor:read
GET  /api/v1/anchoring/log/entries            recent leaves                         perm anchor:read
GET  /api/v1/anchoring/backends               usable ledgers + independence         perm anchor:read
GET  /api/v1/anchoring/consistency?first=&second=   append-only proof               perm anchor:read
POST /api/v1/anchors                          sign the head and publish it          perm anchor:create
GET  /api/v1/anchors                          list                                  perm anchor:read
GET  /api/v1/anchors/{id}                     detail                                perm anchor:read
POST /api/v1/anchors/{id}/refresh             has it confirmed yet?                 perm anchor:read
GET  /api/v1/anchors/{id}/verify              recompute root + signature + ledger    perm anchor:read
GET  /api/v1/anchors/{id}/receipt             raw backend receipt (.ots etc.)       perm anchor:read
GET  /api/v1/evidence/{id}/proof              offline-verifiable proof bundle       perm anchor:read
POST /api/v1/anchoring/verify-bundle          re-check a bundle (convenience)       perm anchor:read
```

`GET /api/v1/evidence/{id}/proof` returns a self-contained bundle — manifest,
leaf index, audit path, signed tree head, public key, anchor receipt — and
**no evidence bytes**. Verify it independently:

```bash
python3 scripts/verify_anchor.py proof.json \
    --evidence-file sysmon.jsonl --expect-key-id <published key id>
```

`GET /api/v1/anchors/{id}/verify` reports three checks separately, because
they fail for different reasons:

```json
{ "verified": true, "root_recomputed": true, "signature_valid": true,
  "independence": "PUBLIC_BLOCKCHAIN", "status": "CONFIRMED",
  "detail": "Root recomputed from the log matches the anchor. Tree-head signature is valid. ..." }
```

---

## Planned — returns 501 today

| Endpoint | Sprint |
|---|---|
| `GET  /api/v1/entities`, `GET /api/v1/entities/{id}` | 3 |
| `GET  /api/v1/graph/neighbourhood` | 3 |
| `POST /api/v1/detections/sigma/run` | 4 |
| `POST /api/v1/detections/yara/scan` | 4 |
| `GET  /api/v1/hunt/rare`, `GET /api/v1/hunt/first-seen` | 4 |
| `POST /api/v1/patterns/find-similar` | 5 |
| `POST /api/v1/patterns/sequences/run` | 5 |
| `GET  /api/v1/anomalies`, `GET /api/v1/anomalies/beacons` | 5 |
| `POST /api/v1/ai/investigate` | 6 |
| `POST /api/v1/entities/{id}/reveal` | 7 |
| `POST /api/v1/reports/generate` | 7 |
| `GET  /api/v1/threatintel/enrich` | 7 |
| `GET  /api/v1/cases/{id}/evidence-gaps` | 7 |
| `GET  /api/v1/cases/{id}/contradictions` | 7 |

Request/response schemas for these are already defined as Pydantic models
next to each stub, so the contract is stable before the implementation lands.

### Reserved shapes

`POST /api/v1/patterns/find-similar` →
```json
{ "matches": [ {"case": "CASE-0018", "similarity": 0.94},
               {"case": "CASE-0031", "similarity": 0.86} ] }
```

`POST /api/v1/ai/investigate` →
```json
{ "summary": "...", "facts": [], "inferences": [], "hypotheses": [],
  "unknowns": [], "evidence": [], "confidence": 0.91 }
```
A `facts[]` entry without at least one evidence reference is rejected by the
response validator (§36 guardrail).
