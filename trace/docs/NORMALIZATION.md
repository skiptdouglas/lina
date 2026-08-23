# TRACE — Normalization, Search and Timeline

> Four vendors, four formats, one chronology — and every event on it still
> addresses the exact bytes it came from.

```
Raw artifact (object storage)
    ↓  fresh copy, never the upload stream
Parser plugin
    ↓  one leaf per record, byte-accurate locator
Normalized event  (OCSF-inspired subset)
    ↓
Event store   ClickHouse (production) · SQL (development)
    ↓
Search · Timeline · click-through back to the original record
```

---

## 1. What parsing does and does not claim

A parse report says exactly what happened, including what did not:

```json
{ "parse_status": "PARSED", "parser_id": "sysmon-json",
  "events_produced": 13, "records_read": 13, "records_skipped": 0,
  "unrecognised": 4, "unrecognised_types": {"EventID 15": 4},
  "truncated": false, "detail": "sysmon-json: 13 event(s) from 13 record(s). …" }
```

**Coverage is a forensic question, not a feature list.** An analyst concluding
"no image loads occurred" needs to know whether TRACE understood event 7 at
all. So unrecognised records are counted by type and reported, malformed lines
are counted and skipped rather than aborting the parse, and a truncated read
says so.

`GET /api/v1/ingestion/parsers` lists every parser and the record types it
maps. If a record type is not in that list, TRACE did not look at it.

### Statuses

| Status | Means |
|---|---|
| `PENDING` | Stored, not yet queued |
| `QUEUED` | Waiting for the parse worker |
| `PARSING` | In progress |
| `PARSED` | Events produced |
| `UNSUPPORTED` | Read, but nothing mapped — the artifact is still stored and verifiable |
| `FAILED` | The parse errored; raw evidence untouched, re-parseable once fixed |

---

## 2. Parsers

| Parser | Source types | Records mapped |
|---|---|---|
| `sysmon-json` | `SYSMON` | Events **1** ProcessCreate, **3** NetworkConnect, **7** ImageLoad, **10** ProcessAccess, **11** FileCreate, **13** RegistrySet, **22** DnsQuery |
| `windows-security-json` | `WINDOWS_SECURITY`, `WINDOWS_EVTX` | 4624/4625/4634 logon, 4648 explicit credentials, 4672 privileges, 4688 process create, 5140/5145 share access, **1102/104 log cleared** |
| `zeek-json` | `ZEEK` | conn, dns, http, ssl, files |
| `suricata-eve-json` | `SURICATA` | alert, flow, netflow, dns, http, tls, fileinfo |
| `linux-json` | `LINUX_JSON`, `LINUX_SYSLOG` | journald, auditd exports, generic structured logs |

Two shapes of Windows JSON are accepted — flat keys, and the nested
`{"Event": {"System": …, "EventData": …}}` that `wevtutil` and `evtx_dump`
emit. A parser that only handled its favourite would fail on real exports.

### Judgement encoded in the parsers

* **LSASS access is severity 8+.** Credential access must not sort alongside a
  file write.
* **Log clearing (1102/104) is severity 9.** It is both an attacker action and
  a gap in everything after it — evidence-gap detection keys off exactly this.
* **Suricata severity is inverted, not copied.** Suricata's 1 is *most* severe;
  TRACE's 10 is. Getting that backwards would bury the worst alerts.
* **Unsigned image loads outrank signed ones.** That is why event 7 is
  collected at all.
* **A record with no usable timestamp is skipped, not invented.** An event that
  cannot be placed on a timeline is worse than a missing one.

### Dispatch

Declared `source_type` wins, but only if the parser also recognises the
content. Analysts mislabel uploads; a wrong label degrades into "let me look at
the bytes" rather than "no parser".

---

## 3. Provenance: `raw_reference`

Every event carries a byte-accurate locator into its source artifact:

```
jsonl:<line>:<offset>:<length>
```

`GET /api/v1/evidence/{id}/record?reference=jsonl:12:4096:312` range-reads the
stored object and returns **exactly those bytes** — pulling one record out of a
40 GB image without downloading the image.

That completes the chain the whole platform exists to preserve:

```
Finding → Detection → Event → raw_reference → original bytes
                            → evidence_id  → SHA-256 → anchored Merkle root
```

The locator is bounded on every axis: it is validated against a strict grammar,
refused if it points past the end of the object, and capped by
`TRACE_RECORD_MAX_BYTES`. It is a provenance pointer, not an arbitrary read
primitive.

---

## 4. Clock skew (brief §17)

Original timestamps are **never overwritten**. Every event carries:

| Field | Meaning |
|---|---|
| `original_timestamp` | verbatim from the source |
| `timestamp` | `original + offset`, used for ordering |
| `clock.clock_offset_seconds` | the correction applied |
| `clock.correction_confidence` | 0–1, how trusted the offset is |
| `clock.method` | `NONE` · `NTP_REPORTED` · `COLLECTOR_DELTA` · `CROSS_SOURCE_ANCHOR` · `ANALYST_ASSERTED` |

The offset is supplied at ingest, because the collector is what actually
measures it:

```bash
curl -F "file=@sysmon.jsonl" -F "case_id=CASE-DEMO-001" -F "source=HOST-1" \
     -F "source_type=SYSMON" -F "clock_offset_seconds=-120" \
     -F "clock_offset_confidence=0.6" -F "clock_offset_method=COLLECTOR_DELTA" \
     "$API/evidence"
```

**The offset is deliberately excluded from the anchored manifest.** It is a
*measurement*, revisable when a better one arrives; the original timestamps it
applies to are the committed fact. Re-parsing with a corrected offset changes
the derived events and leaves every existing proof intact.

The timeline flags corrected entries and shows both times, so the ordering is
auditable rather than asserted.

---

## 5. Event storage

Two implementations of one interface, held to a **shared contract test suite**
(`tests/contract/event_store_contract.py`) that runs against both:

| Backend | When | Notes |
|---|---|---|
| `clickhouse` | production, default | Columnar; aggregation pushed into the engine |
| `sql` | development, small deployments, CI | Real implementation, no extra service |

The interface exposes **typed query methods, not raw SQL**. An interface whose
only method is `execute(sql)` is not replaceable — it just moves the coupling.
Each backend writes its own SQL and pushes aggregation into its own engine.

### Nullability is a forensic decision

Ports, PIDs and sizes are nullable in both backends. "Absent" and "zero" are
different facts: PID 0 is a real process, an empty file has size 0. Nullable
costs a null-map byte per value in ClickHouse; conflating them costs evidence.

Strings use `""` for absent, which is lossless because the event model
normalises blank strings away — so `""` can never be a meaningful value.

The column/`extra` split is a **partition, not a copy**: `extra` holds exactly
the remainder after the mapped paths are removed, so
`row_to_event(event_to_row(e)) == e` for any event, asserted field by field.

---

## 6. Search

| Backend | Full text | Fuzzy | Ranking | When |
|---|---|---|---|---|
| `sql` (default) | substring over indexed columns | ✗ | time order | Always correct, no separate index to drift |
| `opensearch` | analyzed | ✓ | relevance | Opt-in |

**Every response reports which backend answered and what it can express.**
"No results" must never be ambiguous between *nothing matched* and *this
backend cannot express that query* — one is an investigative conclusion, the
other is a tooling limitation, and confusing them is how findings get missed.

The OpenSearch index is derived data: rebuildable from the event store, which
is rebuildable from raw evidence. If they disagree, the store wins. Indexing
failures are logged and the parse still succeeds — losing the index costs a
rebuild, failing the parse costs the events.

Searches are audited. Who looked for what is part of the investigation record,
and investigation replay (brief §41) is built from it.

---

## 7. Parsing at scale

Ingest enqueues; a background worker drains. An upload must return as soon as
the evidence is stored and verified — parsing a 40 GB image cannot be on that
path.

**Failure isolation is the design point.** One artifact that cannot be parsed
must not stall the queue or the artifacts behind it. Every job is caught, the
failure is recorded on the evidence row where the UI shows it, and the worker
moves on.

Re-parsing **replaces** an artifact's events rather than appending, so a fixed
parser or a corrected clock offset can be applied without doubling a timeline.

### Limits on untrusted input

Evidence is attacker-influenced by definition — it came from a compromised
machine.

| Limit | Default | Guards against |
|---|---|---|
| `TRACE_PARSE_MAX_RECORDS` | 5,000,000 | Billion-record logs |
| `TRACE_PARSE_MAX_BYTES` | 8 GiB | Oversized artifacts |
| `TRACE_PARSE_MAX_RECORD_BYTES` | 8 MiB | A single 40 GB "line" |
| `TRACE_RECORD_MAX_BYTES` | 4 MiB | Record retrieval as a bulk-read primitive |

Exceeding a limit **truncates and says so** in the parse report. Silent
truncation would read as "that's all there was".

---

## 8. Known limits

| Limit | Consequence | Planned |
|---|---|---|
| Parsing is in-process, not sandboxed | A parser bug affects the API process; limits bound the damage but do not isolate it | Sandboxed worker containers |
| EVTX/PCAP are not parsed natively | Convert to JSON lines first; TRACE stores and verifies them either way | Native readers |
| OpenSearch backend is unverified against a live cluster | Written to the documented API, never run against a real node | Exercise in a deployment |
| No entity resolution yet | `user.entity_id` / `device.entity_id` are empty; the timeline filters on literal values | Sprint 3 |
| Ordering uses one offset per artifact | Per-host skew within a single artifact is not modelled | Cross-source anchoring |
