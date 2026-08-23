-- TRACE analytics database.
-- All statements in deploy/clickhouse are idempotent: they are applied on every
-- API start (TRACE_CLICKHOUSE_APPLY_SCHEMA=true).
CREATE DATABASE IF NOT EXISTS trace;
