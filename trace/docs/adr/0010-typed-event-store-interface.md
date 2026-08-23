# ADR-0010 — The event store interface is typed methods, not raw SQL

**Status:** Accepted

## Context

ADR-0002 makes ClickHouse the primary analytics store and promises it is
replaceable — by Databricks for an enterprise deployment (brief §56), and in
practice by something simpler for a small one.

The obvious interface is `execute(sql) -> rows`. It is also useless. SQL
written for ClickHouse does not run on anything else, so an `execute(sql)`
interface does not decouple anything; it relocates the coupling from the store
to the caller and calls it an abstraction.

There was also a practical problem: ClickHouse could not be run in this
repository's CI, so an implementation written only against it would ship
entirely untested.

## Decision

`EventStore` exposes **typed query methods** — `search(EventQuery)`,
`top_values(dimension)`, `count_for_case()`. What crosses the interface is a
query *description*. Each implementation writes its own SQL and pushes
aggregation into its own engine, which is what ADR-0002 actually asked for.

Two implementations ship:

* `ClickHouseEventStore` — production.
* `SqlEventStore` — SQLAlchemy over the metadata database. A real
  implementation, not a stub: correct everywhere, no extra service, and what
  small deployments and CI use.

A shared behavioural contract (`tests/contract/event_store_contract.py`) is
written once against the interface and run against both, so a second backend
cannot quietly diverge from the first.

## Consequences

* Aggregation still happens in the datastore; Python still only orchestrates.
* The whole Sprint 2 path is testable without infrastructure, which is why it
  arrived with 100+ passing tests rather than a promise.
* Adding Databricks means implementing ~8 methods and running one existing test
  class against it.
* The cost is that a query shape not expressible through `EventQuery` needs an
  interface change. That is the right friction: it forces the question of
  whether every backend can serve it.
