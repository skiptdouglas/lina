# ADR-0001 — Record architecture decisions

**Status:** Accepted

## Context
TRACE makes a number of consequential choices (which store owns what, what may
be substituted, where computation happens). The brief asks for reasonable
architectural decisions to be made and documented rather than confirmed
file-by-file.

## Decision
Every decision that constrains future work is recorded as a short ADR in
`docs/adr/`. ADRs are immutable: a reversal is a new ADR that supersedes.

## Consequences
Reviewers can see why something is the way it is without archaeology.
