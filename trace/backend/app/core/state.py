"""Process-wide application state.

Constructed once during startup and attached to ``app.state.trace`` so that
request dependencies never build clients per request.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.audit.sinks import AuditMirror, ClickHouseAuditMirror, NullAuditMirror
from app.core.analytics import AnalyticsStore, NullAnalyticsStore
from app.core.clickhouse import ClickHouseAnalyticsStore
from app.core.config import Settings
from app.core.db import Database
from app.core.security import Authenticator, build_authenticator
from app.evidence.storage import InMemoryObjectStore, MinioObjectStore, ObjectStore
from app.ingestion.queue import IngestionQueue, InMemoryIngestionQueue


@dataclass(slots=True)
class AppState:
    settings: Settings
    database: Database
    object_store: ObjectStore
    analytics: AnalyticsStore
    audit_mirror: AuditMirror
    authenticator: Authenticator
    queue: IngestionQueue


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


def build_state(settings: Settings) -> AppState:
    analytics = build_analytics(settings)
    mirror: AuditMirror = (
        ClickHouseAuditMirror(analytics)
        if settings.audit_clickhouse_mirror and settings.clickhouse_enabled
        else NullAuditMirror()
    )
    return AppState(
        settings=settings,
        database=Database(settings.database_url, echo=settings.database_echo),
        object_store=build_object_store(settings),
        analytics=analytics,
        audit_mirror=mirror,
        authenticator=build_authenticator(settings),
        queue=InMemoryIngestionQueue(),
    )
