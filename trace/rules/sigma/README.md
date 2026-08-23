# Sigma rules

Sigma rules live here and are compiled to ClickHouse SQL in Sprint 4, so they
run against historical data rather than only against a live stream
(docs/ROADMAP.md#sprint-4).

* `POST /api/v1/detections/sigma/run` returns **501 NOT_IMPLEMENTED** today.
* The rules below are real Sigma and are used as fixtures for the compiler.
* Detection objects carry `tactic` / `technique` / `subtechnique`
  (docs/DATA_MODEL.md §7), and every detection references the event IDs it
  fired on.

Layout: `rules/sigma/<category>/<rule>.yml`.
