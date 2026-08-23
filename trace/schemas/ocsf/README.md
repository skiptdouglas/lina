# Event schema

TRACE uses an **OCSF-inspired subset**, not the full OCSF specification — the
brief is explicit that implementing all of OCSF in the first iteration is not
the goal (§10).

* Canonical definition: `backend/app/normalization/schema.py`
  (`NormalizedEvent`, Pydantic — the enforcement point).
* Storage layout: `deploy/clickhouse/003_events.sql`.
* Narrative: [`docs/DATA_MODEL.md` §4](../../docs/DATA_MODEL.md).

Two properties are non-negotiable and are enforced by the model rather than by
convention:

1. `evidence_id` and `raw_reference` are required on every event. An event that
   cannot be walked back to the original bytes must never reach the analytics
   store (docs/ARCHITECTURE.md §7).
2. `original_timestamp` is stored verbatim alongside the clock-corrected
   `timestamp`. Original timestamps are never overwritten (brief §17).

`ocsf-mapping.json` records how TRACE fields line up with OCSF classes so the
subset can grow toward the specification without a rename.
