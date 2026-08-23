# Collectors

Collectors acquire telemetry and hand it to the ingestion API. They are the
first link in the chain of custody, so each one records **what** it collected,
**when**, **from where**, and **how** — the `collector` and
`acquisition_method` fields on every evidence object (docs/DATA_MODEL.md §2).

Sprint 1 ships the *contract* and configuration for each collector, plus a
working manual/scripted path: anything a collector can produce can be posted
today with `POST /api/v1/evidence`. Packaged agents land alongside their
parsers in Sprint 2 (docs/ROADMAP.md#sprint-2).

## The contract

Every collector, whatever the platform:

1. Preserves the original artifact. It never re-encodes, filters, truncates or
   "cleans" what it collected — TRACE normalizes, the collector does not.
2. Sends the raw artifact to `POST /api/v1/evidence` with:
   `case_id`, `source`, `source_type`, `collector` (name/version),
   `acquisition_method`, and `original_path` where one exists.
3. Uses a `SERVICE`-role token, scoped to its tenant, with no
   `evidence:download` permission — a collector writes, it does not read.
4. Computes SHA-256 locally where it can, so the digest can be compared with
   the one TRACE reports back. Any mismatch is a collection failure.
5. Records collection gaps explicitly. A collector that was offline must say
   so; a silent gap is indistinguishable from an attacker clearing logs
   (evidence-gap detection, docs/ROADMAP.md#sprint-7).

## Directory map

| Directory | Source | Parser sprint |
|---|---|---|
| `sysmon/` | Sysmon operational log (events 1, 3, 7, 10, 11, 13, 22) | 2 |
| `windows/` | Windows Security / System / PowerShell logs | 2 |
| `linux/` | auditd, journald and JSON application logs | 2 |
| `zeek/` | Zeek JSON logs (`conn`, `dns`, `http`, `ssl`, `files`) | 2 |
| `suricata/` | Suricata EVE JSON (alerts, flows, files) | 2 |

Each directory carries the collection configuration TRACE expects and the
record types its parser will support.
