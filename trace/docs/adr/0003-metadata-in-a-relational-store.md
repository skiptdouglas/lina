# ADR-0003 — Case, evidence and audit metadata live in a relational store

**Status:** Accepted

## Context
The service list in the brief is ClickHouse, OpenSearch, MinIO, Memgraph and
Ollama. Cases, evidence metadata and the audit chain are small, highly
mutable (case status, legal hold), and need transactional integrity and
ordered writes — the opposite of ClickHouse's design centre.

## Decision
A relational store, accessed through SQLAlchemy 2.0 async, owns case and
evidence metadata, the audit chain of record, and the entity/pseudonym
registries. It is configured by `TRACE_DATABASE_URL`:

* MVP default: SQLite (`sqlite+aiosqlite`) on a Docker volume — no extra
  service, works out of the box.
* Production: PostgreSQL — change the URL only.

Audit records are additionally mirrored, append-only, into ClickHouse
(`trace.audit_log`) for cheap long-term retention and fast querying.

## Consequences
* No new service in the MVP compose file.
* SQLite's single-writer limitation is acceptable for one API replica and is
  documented as the trigger for moving to PostgreSQL.
* The mirror is best-effort by design; the relational chain is the record.
