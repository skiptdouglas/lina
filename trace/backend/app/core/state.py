"""Process-wide application state.

Constructed once during startup and attached to ``app.state.trace`` so that
request dependencies never build clients per request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.anchoring.backends.base import AnchorBackend
from app.anchoring.backends.evm import EvmAnchorBackend
from app.anchoring.backends.file_receipt import FileReceiptAnchorBackend
from app.anchoring.backends.opentimestamps_backend import (
    DEFAULT_CALENDARS,
    OpenTimestampsAnchorBackend,
)
from app.anchoring.signing import Signer, load_signer
from app.audit.sinks import AuditMirror, ClickHouseAuditMirror, NullAuditMirror
from app.core.analytics import AnalyticsStore, NullAnalyticsStore
from app.core.clickhouse import ClickHouseAnalyticsStore
from app.core.config import Settings
from app.core.db import Database
from app.core.security import Authenticator, build_authenticator
from app.evidence.storage import InMemoryObjectStore, MinioObjectStore, ObjectStore
from app.ingestion.queue import IngestionQueue, InMemoryIngestionQueue

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppState:
    settings: Settings
    database: Database
    object_store: ObjectStore
    analytics: AnalyticsStore
    audit_mirror: AuditMirror
    authenticator: Authenticator
    queue: IngestionQueue
    #: None when anchoring is disabled or no signing key could be resolved.
    signer: Signer | None
    anchor_backends: dict[str, AnchorBackend]


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store == "memory":
        return InMemoryObjectStore()
    return MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )


def build_analytics(settings: Settings) -> AnalyticsStore:
    if not settings.clickhouse_enabled:
        return NullAnalyticsStore("TRACE_CLICKHOUSE_ENABLED=false")
    return ClickHouseAnalyticsStore(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
    )


def build_signer(settings: Settings) -> Signer | None:
    """Resolve the log signing key, or disable anchoring loudly.

    A missing key disables anchoring rather than falling back to something
    weaker — an unsigned tree head is not an anchor.
    """
    if not settings.anchor_enabled:
        return None
    try:
        return load_signer(
            key_path=settings.anchor_signing_key_path or None,
            key_seed_b64=settings.anchor_signing_key_seed or None,
            allow_generate=settings.anchor_allow_key_generation,
            generated_key_path=settings.anchor_signing_key_path or None,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error(
            "Evidence anchoring is DISABLED: %s. Anchoring endpoints will report that "
            "no signing key is configured.",
            exc,
        )
        return None


def build_anchor_backends(settings: Settings) -> dict[str, AnchorBackend]:
    """The process-wide, stateless backends, keyed by name.

    The ``local`` ledger backend is deliberately absent: it writes to TRACE's
    own database and is constructed per request with the caller's session
    (see :class:`~app.anchoring.service.AnchoringService`).

    ``available()`` reports at call time whether each backend can actually be
    used. One that cannot reach its dependency says so rather than silently
    anchoring somewhere weaker.
    """
    if not settings.anchor_enabled:
        return {}

    backends: dict[str, AnchorBackend] = {
        "file": FileReceiptAnchorBackend(settings.anchor_receipt_dir),
        "opentimestamps": OpenTimestampsAnchorBackend(
            calendars=settings.ots_calendar_list or DEFAULT_CALENDARS,
            timeout=settings.anchor_ots_timeout_seconds,
        ),
    }
    if settings.anchor_evm_rpc_url and settings.anchor_evm_private_key:
        backends["evm"] = EvmAnchorBackend(
            rpc_url=settings.anchor_evm_rpc_url,
            private_key=settings.anchor_evm_private_key,
            chain_id=settings.anchor_evm_chain_id or None,
            contract_address=settings.anchor_evm_contract or None,
            confirmations=settings.anchor_evm_confirmations,
        )
    return backends


def build_state(settings: Settings) -> AppState:
    analytics = build_analytics(settings)
    mirror: AuditMirror = (
        ClickHouseAuditMirror(analytics)
        if settings.audit_clickhouse_mirror and settings.clickhouse_enabled
        else NullAuditMirror()
    )
    database = Database(settings.database_url, echo=settings.database_echo)
    return AppState(
        settings=settings,
        database=database,
        object_store=build_object_store(settings),
        analytics=analytics,
        audit_mirror=mirror,
        authenticator=build_authenticator(settings),
        queue=InMemoryIngestionQueue(),
        signer=build_signer(settings),
        anchor_backends=build_anchor_backends(settings),
    )
