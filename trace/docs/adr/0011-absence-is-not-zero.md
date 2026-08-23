# ADR-0011 — Absence and zero are different facts

**Status:** Accepted

## Context

The first event-store schema declared ports, PIDs and byte counts as
`NOT NULL DEFAULT 0`, which is the conventional choice for a columnar store:
nullable columns cost a null-map byte per value and blunt index efficiency.

The shared contract test caught what that convention costs in a forensic
context. An event whose source did not record a parent PID came back with
`parent_pid = 0`. But PID 0 is the System Idle Process — a real value. An empty
file has size 0. A flow that carried no bytes has `bytes_out = 0`.

Conflating "the source did not tell us" with "the source told us zero" is
silent evidence loss, and it is exactly the kind that surfaces as a wrong
conclusion rather than an error.

## Decision

Ports, PIDs and sizes are **nullable in both backends** — `Nullable(UInt32)` in
ClickHouse, nullable columns in SQL. Round-trip fidelity is asserted field by
field: what goes into the store is what comes out.

Strings keep the columnar convention of `""` for absent, because that *is*
lossless here — the event model normalises blank strings to `None` at
validation, so `""` can never be a meaningful value. That property is enforced
at the model rather than left to each parser to remember.

## Consequences

* A null map costs roughly one byte per value per nullable column. Accepted:
  conflating absence with zero costs evidence.
* Analysts can distinguish "no parent process recorded" from "parent PID 0",
  which matters when reconstructing a process tree.
* Any future column must answer the question explicitly: is zero a real value
  for this field? If yes, it is nullable.
