-- First-seen / last-seen / rarity roll-up (Sprints 3-4).
-- Aggregation happens in ClickHouse, not in Python (docs/ARCHITECTURE.md §3).
CREATE TABLE IF NOT EXISTS trace.entity_activity
(
    tenant_id   LowCardinality(String),
    dimension   LowCardinality(String),
    value       String,
    first_seen  SimpleAggregateFunction(min, DateTime64(3, 'UTC')),
    last_seen   SimpleAggregateFunction(max, DateTime64(3, 'UTC')),
    event_count SimpleAggregateFunction(sum, UInt64),
    host_count  AggregateFunction(uniq, String),
    user_count  AggregateFunction(uniq, String)
)
ENGINE = AggregatingMergeTree
ORDER BY (tenant_id, dimension, value);
