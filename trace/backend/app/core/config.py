"""Application configuration.

Every setting is supplied by the environment with the ``TRACE_`` prefix.
Secrets have **no defaults**: a misconfigured deployment must fail loudly
rather than start with a well-known password.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- runtime -----------------------------------------------------------
    env: Environment = "dev"
    debug: bool = False
    api_root_path: str = ""
    log_level: str = "INFO"

    # ---- authn / authz -----------------------------------------------------
    auth_mode: Literal["dev", "token"] = "token"
    #: JSON: {"<token>": {"subject": "...", "roles": ["INVESTIGATOR"], "tenant": "default"}}
    api_tokens: str = ""
    default_tenant: str = "default"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # ---- metadata database (ADR-0003) -------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/trace.db"
    database_echo: bool = False

    # ---- object storage (evidence) ----------------------------------------
    object_store: Literal["minio", "memory"] = "minio"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False
    minio_region: str | None = None
    evidence_bucket: str = "trace-evidence"

    # ---- evidence handling -------------------------------------------------
    evidence_max_upload_bytes: int = 5 * 1024**3  # 5 GiB
    evidence_spool_max_memory_bytes: int = 8 * 1024**2
    evidence_read_chunk_bytes: int = 1024**2
    #: Re-read and re-hash the stored object before committing metadata (ADR-0005).
    evidence_verify_on_ingest: bool = True

    # ---- clickhouse --------------------------------------------------------
    clickhouse_enabled: bool = True
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 8123
    clickhouse_user: str = "trace"
    clickhouse_password: str = ""
    clickhouse_database: str = "trace"
    #: Startup applies deploy/clickhouse/*.sql when true.
    clickhouse_apply_schema: bool = True
    #: Overrides the schema directory; empty means "resolve relative to the repo layout".
    clickhouse_schema_dir: str = ""

    # ---- services used from Sprint 2 onwards -------------------------------
    opensearch_url: str = "http://opensearch:9200"
    memgraph_host: str = "memgraph"
    memgraph_port: int = 7687
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"

    # ---- parsing / normalization ------------------------------------------
    #: Parse automatically once evidence is ingested.
    parse_on_ingest: bool = True
    #: Bounds applied while reading attacker-influenced evidence.
    parse_max_records: int = 5_000_000
    parse_max_bytes: int = 8 * 1024**3
    parse_max_record_bytes: int = 8 * 1024**2
    #: Largest single raw record served by GET /evidence/{id}/record.
    record_max_bytes: int = 4 * 1024**2
    #: Event storage: sql | clickhouse
    event_store: str = "clickhouse"
    #: Search: sql | opensearch
    search_backend: str = "sql"
    opensearch_index: str = "trace-events"
    opensearch_verify_certs: bool = True
    opensearch_username: str = ""
    opensearch_password: str = ""

    # ---- evidence anchoring (docs/ANCHORING.md) ---------------------------
    anchor_enabled: bool = True
    #: local | opentimestamps | evm | file
    anchor_backend: str = "local"
    #: Append a Merkle leaf for every ingested evidence object.
    anchor_append_on_ingest: bool = True
    #: Periodically anchor the current tree head without an operator asking.
    anchor_auto: bool = False
    anchor_interval_seconds: int = 3600
    anchor_min_new_leaves: int = 1
    #: Ed25519 signing key. A PEM path (mounted secret) or a base64 32-byte seed.
    anchor_signing_key_path: str = "./data/keys/log-signing-key.pem"
    anchor_signing_key_seed: str = ""
    #: Development convenience: generate a key when none exists. Refused in prod.
    anchor_allow_key_generation: bool = False
    anchor_receipt_dir: str = "./data/receipts"
    #: Comma-separated; empty means the OpenTimestamps defaults.
    anchor_ots_calendars: str = ""
    anchor_ots_timeout_seconds: int = 15
    anchor_evm_rpc_url: str = ""
    anchor_evm_private_key: str = ""
    anchor_evm_chain_id: int = 0
    anchor_evm_contract: str = ""
    anchor_evm_confirmations: int = 3

    # ---- audit -------------------------------------------------------------
    audit_fail_closed: bool = True
    audit_clickhouse_mirror: bool = True

    # ---- rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 300
    rate_limit_window_seconds: int = 60

    # ---- derived -----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env in ("staging", "prod")

    @property
    def ots_calendar_list(self) -> tuple[str, ...]:
        return tuple(c.strip() for c in self.anchor_ots_calendars.split(",") if c.strip())

    @property
    def token_registry(self) -> dict[str, dict[str, Any]]:
        """Parsed ``TRACE_API_TOKENS``. Never logged, never echoed in errors."""
        if not self.api_tokens.strip():
            return {}
        try:
            parsed = json.loads(self.api_tokens)
        except json.JSONDecodeError as exc:  # pragma: no cover - config error path
            raise ValueError("TRACE_API_TOKENS is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("TRACE_API_TOKENS must be a JSON object keyed by token")
        return parsed

    # ---- validation --------------------------------------------------------
    @field_validator("api_root_path")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.is_production:
            if self.auth_mode == "dev":
                raise ValueError("TRACE_AUTH_MODE=dev is refused when TRACE_ENV is staging/prod")
            if "*" in self.cors_origin_list:
                raise ValueError("Wildcard CORS origin is refused in staging/prod")
            if self.object_store == "memory":
                raise ValueError("The in-memory object store is for tests only")
            if not self.audit_fail_closed:
                raise ValueError("Audit fail-open is refused in staging/prod")
            if self.anchor_enabled and self.anchor_allow_key_generation:
                raise ValueError(
                    "TRACE_ANCHOR_ALLOW_KEY_GENERATION is refused in staging/prod: an "
                    "ephemeral log signing key makes every tree head unverifiable after "
                    "a restart. Mount a key instead."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test helper — settings are cached for the process lifetime."""
    get_settings.cache_clear()
