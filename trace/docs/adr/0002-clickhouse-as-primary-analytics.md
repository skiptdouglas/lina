# ADR-0002 — ClickHouse is the primary event analytics store

**Status:** Accepted

## Context
TRACE must aggregate over very large event volumes: rarity counts, first/last
seen, frequency baselines, beacon interval histograms. These are columnar
aggregation problems.

## Decision
ClickHouse owns normalized events. Analytics queries are expressed as SQL and
executed in ClickHouse, behind an `AnalyticsStore` interface. Python
orchestrates and shapes results; it does not aggregate.

OpenSearch owns text analysis (command-line search, fuzzy matching, future
vector search) — duplicated *indexes*, not duplicated *truth*.

## Consequences
* Analytics code is SQL that a DBA can read and profile.
* An enterprise deployment can implement `AnalyticsStore` over Databricks /
  Delta Lake without touching route or service code (§56).
* Events are append-only. Corrections are new rows, never in-place edits.
