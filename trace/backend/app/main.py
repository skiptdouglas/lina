"""TRACE API application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.clickhouse import load_schema_statements
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.core.state import build_state

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
#: deploy/clickhouse relative to the repository root; overridable with
#: TRACE_CLICKHOUSE_SCHEMA_DIR so the container layout is not path-arithmetic dependent.
DEFAULT_CLICKHOUSE_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "deploy" / "clickhouse"

DESCRIPTION = """
TRACE — Threat Reconstruction & Analysis Correlation Engine.

AI output is analysis, not evidence. Every conclusion is traceable to an
original, hash-verified evidence object.

Capabilities that are not implemented yet return HTTP 501 with a
`NOT_IMPLEMENTED` body rather than fabricated results — see
`GET /api/v1/capabilities`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = app.state.trace
    settings: Settings = state.settings

    if settings.auth_mode == "dev":
        logger.warning(
            "TRACE is running with TRACE_AUTH_MODE=dev: every request is granted "
            "an ADMIN principal. Never use this outside local development."
        )
    if settings.auth_mode == "token" and not settings.token_registry:
        logger.warning(
            "No API tokens are configured (TRACE_API_TOKENS is empty); "
            "every authenticated route will reject requests."
        )

    await state.database.create_all()

    try:
        await state.object_store.ensure_bucket(settings.evidence_bucket)
    except Exception as exc:  # noqa: BLE001 - startup continues, readiness reports DOWN
        logger.error("Evidence bucket %s is unavailable: %s", settings.evidence_bucket, exc)

    if settings.clickhouse_enabled and settings.clickhouse_apply_schema:
        try:
            schema_dir = (
                Path(settings.clickhouse_schema_dir)
                if settings.clickhouse_schema_dir
                else DEFAULT_CLICKHOUSE_SCHEMA_DIR
            )
            statements = load_schema_statements(schema_dir)
            await state.analytics.apply_schema(statements)
            logger.info("Applied %d ClickHouse schema statement(s)", len(statements))
        except Exception as exc:  # noqa: BLE001 - analytics is not required for Sprint 1
            logger.error("ClickHouse schema bootstrap failed: %s", exc)

    parse_task: asyncio.Task | None = None
    if settings.parse_on_ingest:
        from app.ingestion.worker import ParseWorker  # noqa: PLC0415

        parse_task = asyncio.create_task(ParseWorker(state).run_forever())
        logger.info(
            "Parse worker started; %d parser(s) registered.", len(_parser_count())
        )

    anchor_task: asyncio.Task | None = None
    if settings.anchor_enabled and settings.anchor_auto and state.signer is not None:
        anchor_task = asyncio.create_task(_periodic_anchor(app))
        logger.info(
            "Automatic anchoring enabled: every %ss to backend '%s'.",
            settings.anchor_interval_seconds,
            settings.anchor_backend,
        )
    elif settings.anchor_enabled and state.signer is not None:
        logger.info(
            "Evidence anchoring is available (key %s, default backend '%s'); "
            "anchors are created on demand.",
            state.signer.key_id,
            settings.anchor_backend,
        )

    try:
        yield
    finally:
        for task in (parse_task, anchor_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await state.analytics.close()
        await state.database.dispose()


def _parser_count():  # noqa: ANN202
    from app.normalization.parsers import registry  # noqa: PLC0415

    return registry.all()


async def _periodic_anchor(app: FastAPI) -> None:
    """Anchor each tenant's log on a timer.

    Runs as a system principal. Failures are logged and retried on the next
    tick — a calendar outage must never stop evidence ingestion.
    """
    from sqlalchemy import distinct, select  # noqa: PLC0415

    from app.anchoring.models import MerkleLeaf  # noqa: PLC0415
    from app.anchoring.service import AnchoringService  # noqa: PLC0415
    from app.audit.service import AuditService  # noqa: PLC0415
    from app.core.security import Principal, Role  # noqa: PLC0415

    state = app.state.trace
    settings = state.settings

    while True:
        await asyncio.sleep(settings.anchor_interval_seconds)
        try:
            async with state.database.session_factory() as session:
                tenants = list(
                    (await session.execute(select(distinct(MerkleLeaf.tenant_id)))).scalars().all()
                )
            for tenant_id in tenants:
                async with state.database.session_factory() as session:
                    audit = AuditService(
                        session,
                        mirror=state.audit_mirror,
                        fail_closed=settings.audit_fail_closed,
                    )
                    service = AnchoringService(
                        session,
                        settings=settings,
                        signer=state.signer,
                        backends=state.anchor_backends,
                        audit=audit,
                    )
                    principal = Principal(
                        subject="system.anchor",
                        tenant_id=tenant_id,
                        roles=frozenset({Role.SERVICE}),
                        display_name="Automatic anchoring",
                        auth_method="system",
                    )
                    status = await service.log_status(principal)
                    if status.unanchored_entries < settings.anchor_min_new_leaves:
                        continue
                    anchor = await service.create_anchor(principal, backend_name=None)
                    logger.info(
                        "Anchored %s at tree size %d to %s (%s).",
                        tenant_id,
                        anchor.tree_size,
                        anchor.backend,
                        anchor.status,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a tick failing must not kill the loop
            logger.error("Automatic anchoring tick failed: %s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="TRACE API",
        version="0.1.0",
        description=DESCRIPTION,
        root_path=settings.api_root_path,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )
    app.state.trace = build_state(settings)

    app.add_middleware(
        RateLimitMiddleware,
        requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        enabled=settings.rate_limit_enabled,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-TRACE-Evidence-Id", "X-TRACE-SHA256"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/health", tags=["platform"])
    async def health() -> dict[str, str]:
        """Liveness only — readiness lives at /api/v1/health/ready."""
        return {"status": "ok", "service": "trace-api", "version": app.version}

    return app


app = create_app()
