"""Uniform error handling.

Two shapes are returned by the API:

* ordinary failures — ``{"status": "ERROR", "code": ..., "detail": ...}``
* unimplemented features — the 501 contract described in ADR-0004.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class TraceError(Exception):
    """Base class for errors that map onto an HTTP response."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}

    def to_payload(self) -> dict[str, Any]:
        return {"status": "ERROR", "code": self.code, "detail": self.detail, **self.extra}


class NotFound(TraceError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(TraceError):
    status_code = 409
    code = "CONFLICT"


class Unauthorized(TraceError):
    status_code = 401
    code = "UNAUTHORIZED"


class Forbidden(TraceError):
    status_code = 403
    code = "FORBIDDEN"


class ValidationFailure(TraceError):
    status_code = 422
    code = "VALIDATION_FAILED"


class PayloadTooLarge(TraceError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"


class RateLimited(TraceError):
    status_code = 429
    code = "RATE_LIMITED"


class EvidenceIntegrityError(TraceError):
    """Raised when stored evidence cannot be proven to match what was received."""

    status_code = 500
    code = "EVIDENCE_INTEGRITY_FAILURE"


class StorageUnavailable(TraceError):
    status_code = 503
    code = "STORAGE_UNAVAILABLE"


class AuditWriteFailure(TraceError):
    """Fail-closed auditing: the action is rejected if it cannot be recorded."""

    status_code = 500
    code = "AUDIT_WRITE_FAILED"


class FeatureNotImplemented(TraceError):
    """A capability that is planned but deliberately not faked (ADR-0004)."""

    status_code = 501
    code = "NOT_IMPLEMENTED"

    def __init__(
        self,
        feature: str,
        *,
        planned_sprint: int,
        detail: str | None = None,
        reference: str | None = None,
    ) -> None:
        super().__init__(detail or f"{feature} is not implemented yet.")
        self.feature = feature
        self.planned_sprint = planned_sprint
        self.reference = reference or f"docs/ROADMAP.md#sprint-{planned_sprint}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "NOT_IMPLEMENTED",
            "feature": self.feature,
            "planned_sprint": self.planned_sprint,
            "detail": self.detail,
            "reference": self.reference,
        }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(TraceError)
    async def _trace_error(_: Request, exc: TraceError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthorized) else None
        return JSONResponse(exc.to_payload(), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ERROR",
                "code": "VALIDATION_FAILED",
                "detail": "Request validation failed.",
                "errors": jsonable_encoder(exc.errors()),
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ERROR",
                "code": f"HTTP_{exc.status_code}",
                "detail": exc.detail if isinstance(exc.detail, str) else "Request failed.",
            },
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )
