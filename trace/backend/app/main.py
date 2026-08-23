"""TRACE API application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
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

    try:
        yield
    finally:
        await state.analytics.close()
        await state.database.dispose()


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
