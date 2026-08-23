# ADR-0004 — Unimplemented features return 501, never fabricated data

**Status:** Accepted

## Context
Large parts of TRACE arrive in later sprints. A forensic tool that returns a
plausible-looking similarity score from a stub is actively dangerous: an
investigator cannot tell analysis from decoration.

## Decision
Unimplemented capabilities raise `FeatureNotImplemented` → HTTP 501 with
`{"status": "NOT_IMPLEMENTED", "feature", "planned_sprint", "detail",
"reference"}`. `GET /api/v1/capabilities` enumerates the full map, and the UI
renders a NOT IMPLEMENTED panel from it rather than an empty chart.

Request/response Pydantic models are written *now* so the contract is stable
before the implementation lands.

## Consequences
* No mock data anywhere in the product path. Fixtures exist only in tests.
* `tests/unit/test_not_implemented.py` asserts the contract holds for every
  stub route.
