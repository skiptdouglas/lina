-- Append-only mirror of the chain-of-custody records (ADR-0003, ADR-0006).
-- The authoritative, hash-chained copy lives in the metadata store; this table
-- exists for cheap long-term retention and fast querying.
CREATE TABLE IF NOT EXISTS trace.audit_log
(
    audit_id     String,
    tenant_id    LowCardinality(String),
    sequence     UInt64,
    timestamp    DateTime64(3, 'UTC'),
    actor        String,
    actor_type   LowCardinality(String),
    action       LowCardinality(String),
    case_id      String,
    evidence_id  String,
    entity_id    String,
    source_ip    String,
    user_agent   String,
    reason       String,
    details      String,
    prev_hash    FixedString(64),
    record_hash  FixedString(64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, timestamp, sequence)
SETTINGS index_granularity = 8192;
