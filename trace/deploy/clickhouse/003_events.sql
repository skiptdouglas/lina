-- Normalized events (docs/DATA_MODEL.md §4).
-- Populated from Sprint 2; the table is created now so the schema is reviewable
-- and the analytics contract is fixed before parsers land.
--
-- Hot fields are materialised as top-level columns so ClickHouse indexes them;
-- the long tail lives in `extra`.
--
-- Ports, PIDs and sizes are Nullable on purpose. "Absent" and "zero" are
-- different facts in forensics: PID 0 is a real process and an empty file has
-- size 0. Nullable costs a null-map byte per value; conflating them costs
-- evidence. Strings stay non-nullable with '' meaning absent, which is
-- lossless because the event model normalises blank strings away.
CREATE TABLE IF NOT EXISTS trace.events
(
    event_id            String,
    tenant_id           LowCardinality(String),
    case_id             String,

    -- Clock skew: the original value is never overwritten (brief §17).
    timestamp           DateTime64(3, 'UTC'),
    original_timestamp  DateTime64(3, 'UTC'),
    clock_offset        Float64 DEFAULT 0,
    correction_confidence Float32 DEFAULT 1,

    event_type          LowCardinality(String),
    category            LowCardinality(String),
    severity            UInt8 DEFAULT 0,

    user_name           String,
    user_domain         String,
    user_sid            String,
    user_entity_id      String,

    device_hostname     String,
    device_ip           Array(String),
    device_entity_id    String,

    src_ip              String,
    src_port            Nullable(UInt16),
    dst_ip              String,
    dst_port            Nullable(UInt16),
    dst_domain          String,

    process_pid         Nullable(UInt32),
    process_guid        String,
    process_name        String,
    process_path        String,
    process_command_line String,
    process_sha256      String,
    parent_pid          Nullable(UInt32),
    parent_guid         String,
    parent_name         String,

    file_path           String,
    file_name           String,
    file_sha256         String,
    file_size           Nullable(UInt64),

    network_protocol    LowCardinality(String),
    network_direction   LowCardinality(String),
    network_bytes_in    Nullable(UInt64),
    network_bytes_out   Nullable(UInt64),

    -- Provenance. Required: an event that cannot be walked back to evidence
    -- must never reach this table (docs/ARCHITECTURE.md §7).
    evidence_id         String,
    raw_reference       String,

    extra               String,

    INDEX idx_cmdline process_command_line TYPE tokenbf_v1(4096, 3, 0) GRANULARITY 4,
    INDEX idx_process_name process_name TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_dst_ip dst_ip TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_file_sha256 file_sha256 TYPE bloom_filter(0.01) GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, case_id, timestamp, event_id)
SETTINGS index_granularity = 8192;
