# Correlation and sequence rules

Sequence definitions (brief §22) are configuration, not code, so an analyst can
add one without a deployment. Consumed by
`POST /api/v1/patterns/sequences/run` in Sprint 5 (**501** today).

Each definition names ordered steps, a time window and the scope the steps must
share (a host, a user, or a process tree).
