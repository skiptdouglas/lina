# TRACE — Data Model

Status legend: **[S1]** implemented in Sprint 1 · **[Sn]** planned for sprint *n*

---

## 1. Case  **[S1]**

Metadata DB table `cases`.

| Field | Type | Notes |
|---|---|---|
| `case_id` | str PK | Human readable, `CASE-0042`, or explicit e.g. `CASE-DEMO-001` |
| `tenant_id` | str | Isolation boundary, indexed on every query |
| `title` | str | |
| `description` | str? | |
| `status` | enum | `OPEN`, `IN_PROGRESS`, `CONTAINMENT`, `CLOSED`, `ARCHIVED` |
| `severity` | enum | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `investigator` | str? | Principal subject of the lead investigator |
| `tags` | json[] | |
| `created_at` / `updated_at` | datetime UTC | |
| `closed_at` | datetime? | |

`entities`, `evidence`, `findings` from §40 of the brief are **relations**,
not columns; they are returned by the API as counts plus sub-resource links
so a case with 400k evidence objects still serializes.

---

## 2. Evidence  **[S1]**

Metadata DB table `evidence`. Bytes live in MinIO and are never mutated.

| Field | Type | Notes |
|---|---|---|
| `evidence_id` | str PK | `EVD-<uuid4hex>` |
| `case_id` | str FK | |
| `tenant_id` | str | |
| `source` | str | Where it came from, e.g. `FINANCE-LAPTOP-07` |
| `source_type` | enum | `SYSMON`, `WINDOWS_SECURITY`, `LINUX_JSON`, `ZEEK`, `SURICATA`, `PCAP`, `MEMORY_IMAGE`, `DISK_IMAGE`, `FILE`, `OTHER` |
| `original_filename` | str | Client-supplied, sanitised for display only |
| `original_path` | str? | Path on the source system |
| `collection_timestamp` | datetime | When the collector acquired it |
| `original_timestamp` | datetime? | mtime / earliest record time |
| `collector` | str | Tool + version, e.g. `manual-upload/1.0` |
| `acquisition_method` | enum | `LIVE_COLLECTION`, `DISK_ACQUISITION`, `MEMORY_ACQUISITION`, `LOG_EXPORT`, `API_PULL`, `MANUAL_UPLOAD`, `AGENT_STREAM` |
| `size` | int | Bytes, as stored |
| `sha256` | str(64) | Computed during streaming ingest |
| `mime_type` | str | Declared + guessed, see `mime_type_source` |
| `storage_bucket` | str | |
| `storage_key` | str | `{tenant}/{case}/{evidence_id}/{safe_filename}` |
| `retention_policy` | str | Named policy, default `default-365d` |
| `legal_hold` | bool | Blocks deletion/expiry unconditionally |
| `parse_status` | enum | `PENDING`, `QUEUED`, `PARSING`, `PARSED`, `FAILED`, `UNSUPPORTED` |
| `last_verified_at` | datetime? | Last integrity verification |
| `last_verification_result` | enum? | `VERIFIED`, `MISMATCH`, `MISSING`, `ERROR` |
| `created_at` | datetime | |

**Storage key is derived by TRACE, never by the client** — an uploaded
`../../etc/passwd` filename cannot influence the object key.

---

## 3. Audit record / chain of custody  **[S1]**

Table `audit_records` (+ append-only ClickHouse mirror `trace.audit_log`).

| Field | Type | Notes |
|---|---|---|
| `audit_id` | str PK | |
| `sequence` | int | Monotonic per tenant; gaps are detectable |
| `timestamp` | datetime UTC | |
| `actor` | str | Principal subject |
| `actor_type` | enum | `USER`, `SERVICE`, `SYSTEM` |
| `action` | enum | `COLLECT` `STORE` `VERIFY` `VIEW` `PARSE` `SEARCH` `EXPORT` `DOWNLOAD` `AI_ACCESS` `IDENTITY_REVEAL` `REPORT` `CASE_CREATE` `CASE_UPDATE` `DETECTION_RUN` `LOGIN` `AUTH_FAILURE` |
| `case_id` / `evidence_id` / `entity_id` | str? | Subjects of the action |
| `source_ip` | str? | |
| `user_agent` | str? | |
| `reason` | str? | **Required** for `IDENTITY_REVEAL`, `EXPORT`, `DOWNLOAD` |
| `details` | json | Action-specific, e.g. hashes compared |
| `prev_hash` | str(64) | Hash of the previous record in the chain |
| `record_hash` | str(64) | `sha256(canonical_json(record) + prev_hash)` |

### Chain integrity

Records form a per-tenant hash chain. `GET /api/v1/audit/verify-chain`
recomputes every link and reports the first divergence. Deleting a record
breaks the chain at the next record; editing one breaks it at itself.

*Limitation (documented, not hidden):* ordering is serialized by an
in-process lock, which is correct for the single-writer MVP. Multi-writer
deployments need a database sequence or a dedicated chain writer —
tracked in ROADMAP as `audit-distributed-chain`.

---

## 4. Normalized event (OCSF-inspired)  **[S2]**

ClickHouse table `trace.events`. Deliberately a *subset* of OCSF —
the full specification is not implemented in the first iteration.

```jsonc
{
  "event_id": "EVT-...",
  "timestamp": "",            // normalized, UTC, clock-skew corrected
  "original_timestamp": "",   // exactly as it appeared in the source
  "event_type": "PROCESS_CREATE",
  "category": "PROCESS",      // PROCESS|NETWORK|FILE|REGISTRY|AUTH|DNS|EMAIL|ALERT|SYSTEM
  "severity": 0,
  "case_id": "CASE-0042",
  "user": {},                 // name, domain, sid, upn, entity_id
  "device": {},               // hostname, ip[], os, entity_id
  "source": {},               // ip, port, geo
  "destination": {},          // ip, port, domain
  "process": {},              // pid, guid, name, path, cmdline, hashes, parent_*
  "file": {},                 // path, name, hashes, size
  "network": {},              // protocol, direction, bytes_in/out, packets
  "raw_reference": "",        // record locator inside the raw object
  "evidence_id": ""           // provenance — REQUIRED, never null
}
```

Nested objects are stored as ClickHouse nested/`Map` columns; hot fields
(`timestamp`, `case_id`, `event_type`, `device.hostname`, `user.name`,
`process.name`, `process.command_line`, hashes, IPs) are materialised as
top-level columns for index use. Schema in
[`deploy/clickhouse/002_events.sql`](../deploy/clickhouse/002_events.sql).

### Clock skew  **[S2]**

Timestamps are never overwritten:

| Field | Meaning |
|---|---|
| `original_time` | verbatim from the source |
| `corrected_time` | `original_time + clock_offset` |
| `clock_offset` | signed seconds, per source/host/collection |
| `correction_confidence` | 0..1, how trusted the offset is |

---

## 5. Entities  **[S3]**

Types: `USER` `HOST` `IP` `DOMAIN` `PROCESS` `FILE` `HASH` `EMAIL`
`APPLICATION` `SERVICE_ACCOUNT` `CLOUD_ACCOUNT` `CERTIFICATE` `URL`.

| Field | Notes |
|---|---|
| `entity_id` | `USER-00042`, `HOST-0018` — stable, pseudonym-safe |
| `entity_type` | one of the above |
| `canonical_name` | resolved primary identifier |
| `aliases[]` | **every** observed identifier, never discarded |
| `first_seen` / `last_seen` / `event_count` | maintained from ClickHouse |
| `attributes` | type-specific |

### Identity resolution  **[S3]**

`DOMAIN\jsmith`, `jsmith`, `jsmith@example.com` and an Entra object UUID all
map to `USER-00042`. Each alias row records *how* the link was made
(`SAME_UPN`, `SAME_SID`, `DIRECTORY_LOOKUP`, `ANALYST_ASSERTED`) and a
confidence, so a wrong merge is auditable and reversible. The original
identifier is preserved on the event and on the alias row.

---

## 6. Graph model  **[S3]**

Nodes mirror entities. Relationships carry provenance:

```
(:User)-[:LOGGED_INTO   {event_ids, first_seen, last_seen, count}]->(:Host)
(:Host)-[:EXECUTED      {event_ids}]->(:Process)
(:Process)-[:SPAWNED    {event_ids}]->(:Process)
(:Process)-[:CREATED    {event_ids}]->(:File)
(:Process)-[:CONNECTED_TO {event_ids}]->(:Ip)
(:User)-[:ACCESSED      {event_ids}]->(:Host)
(:Domain)-[:RESOLVED_TO {event_ids}]->(:Ip)
```

**Every relationship must reference the supporting event IDs.** An edge with
an empty `event_ids` array is rejected at write time — an unsupported
relationship is an assertion, not evidence.

---

## 7. Detections, findings, reports  **[S4+]**

```
Finding { finding_id, case_id, title, confidence, detection_ids[] }
   └─ Detection { detection_id, rule_id, rule_type: SIGMA|YARA|CORRELATION|ANOMALY,
                  mitre: {tactic, technique, subtechnique}, event_ids[], evidence_ids[] }
        └─ Event { event_id, evidence_id, raw_reference }
             └─ Evidence { evidence_id, sha256, storage_key }
```

`detection_ids` / `event_ids` / `evidence_ids` are non-empty by construction.

---

## 8. Anomalies & baselines  **[S5]**

```jsonc
{ "anomaly": "DATA_TRANSFER", "score": 0.94,
  "reason": "38GB transferred vs 30-day median of 620MB",
  "method": "ROBUST_ZSCORE", "baseline_id": "...", "event_ids": [...] }
```

Every anomaly carries a human-readable `reason` and the baseline it was
measured against. Baseline subjects: `USER`, `HOST`, `SERVICE_ACCOUNT`;
peer groups (`user vs department`, `host vs server group`) are modelled now
(`peer_group_id` on the baseline) even though automatic grouping lands later.

---

## 9. Privacy / pseudonymisation  **[S7]**

`pseudonym_mappings` lives in its own table with its own permission
(`identity:reveal`) and, in production, its own encryption key and database
schema. Analytics stores hold **only** pseudonymous identifiers
(`USER-0042`, `HOST-0018`). Reveal is an audited, reason-required action.

---

## 9a. Transparency log and anchors  **[S1]**

Three tables, detailed in [ANCHORING.md](ANCHORING.md).

`merkle_leaves` — one row per log entry. Append-only: no update or delete path
exists anywhere in the application.

| Field | Notes |
|---|---|
| `log_id` | `<tenant>:evidence` or `<tenant>:audit` |
| `leaf_index` | 0-based, dense, unique per log |
| `entry_type` | `EVIDENCE_MANIFEST` / `AUDIT_CHECKPOINT` |
| `entry_hash` | SHA-256 of the canonical entry bytes (display/lookup) |
| `leaf_hash` | `SHA-256(0x00 || canonical bytes)` — what the tree uses |
| `entry_json` | The canonical entry, so bundles can be rebuilt years later |
| `evidence_id` / `case_id` | Back-references |

`anchors` — a signed tree head plus where it was published: `tree_size`,
`root_hash`, `previous_*`, `sth_json`, `signature`, `key_id`, `public_key`,
`backend`, `independence`, `status`, `external_ref`, `receipt_b64`.

`ledger_entries` — the local backend's hash chain: `sequence`, `root_hash`,
`prev_hash`, `entry_hash`.

### Manifest field policy

Only **immutable** evidence fields are committed to a leaf. `legal_hold`,
`retention_policy`, `parse_status`, `last_verified_*` and `notes` are excluded
by design: committing them would mean flipping a legal hold invalidates every
proof issued before the flip. The full table is in
[ANCHORING.md §4](ANCHORING.md).

## 10. ID formats

| Kind | Format |
|---|---|
| Case | `CASE-0042` (zero-padded, 4+ digits) |
| Evidence | `EVD-<32 hex>` |
| Event | `EVT-<32 hex>` |
| Entity | `<TYPE>-<zero-padded number>` |
| Audit | `AUD-<32 hex>` |
| Detection | `DET-<32 hex>` |
| Anchor | `ANC-<32 hex>` |
