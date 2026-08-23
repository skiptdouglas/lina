"""Cross-cutting HTTP middleware: request ids, security headers, rate limiting."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import request_id_var

Handler = Callable[[Request], Awaitable[Response]]

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id to logs and responses, and set security headers."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-caller rate limiting.

    In-process only: correct for a single API replica, which is what the MVP
    compose file runs. Horizontal scale needs a shared counter store — tracked
    in docs/ROADMAP.md as ``audit-distributed-chain``'s sibling work item.
    """

    def __init__(self, app, *, requests: int, window_seconds: int, enabled: bool = True) -> None:
        super().__init__(app)
        self._limit = requests
        self._window = window_seconds
        self._enabled = enabled
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _caller_key(self, request: Request) -> str:
        # Bucket by credential when present so one leaked token cannot exhaust
        # the whole source IP's budget, and vice versa.
        auth = request.headers.get("Authorization", "")
        client = request.client.host if request.client else "unknown"
        return f"{client}|{hash(auth) & 0xFFFFFFFF}"

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        if not self._enabled or not request.url.path.startswith("/api/"):
            return await call_next(request)

        key = self._caller_key(request)
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            retry_after = max(1, int(self._window - (now - bucket[0])))
            return JSONResponse(
                {
                    "status": "ERROR",
                    "code": "RATE_LIMITED",
                    "detail": "Too many requests.",
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
        return await call_next(request)
