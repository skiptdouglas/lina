# ADR-0006 — Chain of custody is hash-chained, not just logged

**Status:** Accepted

## Context
Chain of custody must survive scrutiny. An append-only table still permits a
privileged operator to delete or edit a row.

## Decision
Each audit record stores `prev_hash` and
`record_hash = sha256(canonical_json(record_without_hash) || prev_hash)`,
forming a per-tenant chain with a monotonic `sequence`.
`GET /api/v1/audit/verify-chain` recomputes every link and reports the first
divergence. Audit writes are fail-closed by default.

## Consequences
* Tampering is detectable, not prevented — external timestamping/notarisation
  is the Sprint 7 follow-up.
* Chain ordering is serialized by an in-process lock; multi-replica
  deployments need a shared sequence (backlog: `audit-distributed-chain`).
