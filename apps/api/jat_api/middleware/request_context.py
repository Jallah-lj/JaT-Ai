"""HTTP safety and correlation middleware."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)


_UPLOAD_PATH_SUFFIX = "/documents/upload"
_MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request ID, reject oversized bodies, and add baseline security headers."""

    def __init__(self, app: object, max_request_bytes: int, upload_max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.max_request_bytes = max_request_bytes
        self.upload_max_bytes = upload_max_bytes

    def _effective_limit(self, request: Request) -> int:
        # Document uploads are bounded by the ingestion policy instead of the
        # narrow JSON body limit; the endpoint re-validates the exact byte count.
        content_type = request.headers.get("content-type", "")
        if request.url.path.endswith(_UPLOAD_PATH_SUFFIX) and content_type.startswith(
            "multipart/form-data"
        ):
            return self.upload_max_bytes + _MULTIPART_OVERHEAD_BYTES
        return self.max_request_bytes

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        content_length = request.headers.get("content-length")
        if content_length is not None and int(content_length) > self._effective_limit(request):
            return JSONResponse(
                status_code=413,
                content={
                    "type": "https://jat.ai/problems/request-too-large",
                    "title": "Request body too large",
                    "status": 413,
                    "request_id": request_id,
                },
            )
        start = perf_counter()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)  # type: ignore[operator]
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Cache-Control"] = "no-store"
            logger.info(
                "http_request_complete",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - start) * 1000, 2),
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()
