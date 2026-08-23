# ADR-0005 — Evidence is immutable and verified on write

**Status:** Accepted

## Context
"Never parse the only copy of evidence" and "evidence must never be silently
modified" are the two hard requirements of the platform.

## Decision
1. Uploads stream to a spooled temp file, hashed while streaming.
2. The raw object is written to MinIO under a TRACE-generated key.
3. The stored object is **read back and re-hashed** before metadata is
   committed. A mismatch deletes the orphan and fails the request.
4. Parsers only ever read a fresh copy from object storage; they never
   consume the upload stream.
5. Deletion requires an explicit permission and is refused under legal hold.
   Bucket versioning + object lock are enabled in Sprint 2.

## Consequences
* Ingest costs one extra full read per upload. This is deliberate: the
  guarantee is worth the I/O, and it is configurable
  (`TRACE_EVIDENCE_VERIFY_ON_INGEST`) for bulk backfills where the operator
  accepts the trade-off.
