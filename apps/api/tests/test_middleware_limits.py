"""Upload routes get the ingestion byte budget; everything else stays narrow."""

from __future__ import annotations

import json
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from jat_api.middleware.request_context import (
    _MULTIPART_OVERHEAD_BYTES,
    RequestContextMiddleware,
)


class _BareApp:
    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        raise NotImplementedError


def _middleware(max_request_bytes: int = 1_000_000, upload_max_bytes: int = 25_000_000):
    return RequestContextMiddleware(
        _BareApp(), max_request_bytes=max_request_bytes, upload_max_bytes=upload_max_bytes
    )


def _request(path: str, content_length: int, content_type: str = "application/json") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [
                (b"content-length", str(content_length).encode()),
                (b"content-type", content_type.encode()),
            ],
        }
    )


async def _ok(_: object) -> Response:
    return JSONResponse({"ok": True})


def _status(response: Any) -> int:
    return response.status_code


async def test_regular_routes_keep_the_narrow_limit() -> None:
    middleware = _middleware()
    rejected = await middleware.dispatch(_request("/api/v1/chat", 2_000_000), _ok)
    assert _status(rejected) == 413
    accepted = await middleware.dispatch(_request("/api/v1/chat", 999_000), _ok)
    assert _status(accepted) == 200


async def test_upload_route_uses_the_ingestion_budget() -> None:
    middleware = _middleware()
    path = "/api/v1/knowledge-bases/abc/documents/upload"
    accepted = await middleware.dispatch(
        _request(path, 24_000_000, "multipart/form-data; boundary=x"), _ok
    )
    assert _status(accepted) == 200


async def test_upload_route_still_rejects_beyond_its_budget() -> None:
    middleware = _middleware()
    path = "/api/v1/knowledge-bases/abc/documents/upload"
    rejected = await middleware.dispatch(
        _request(
            path,
            25_000_000 + _MULTIPART_OVERHEAD_BYTES + 1,
            "multipart/form-data; boundary=x",
        ),
        _ok,
    )
    assert _status(rejected) == 413
    assert json.loads(bytes(rejected.body))["title"] == "Request body too large"


async def test_upload_budget_requires_multipart_content_type() -> None:
    middleware = _middleware()
    path = "/api/v1/knowledge-bases/abc/documents/upload"
    rejected = await middleware.dispatch(_request(path, 2_000_000, "application/json"), _ok)
    assert _status(rejected) == 413


def test_middleware_remains_starlette_compatible() -> None:
    assert issubclass(RequestContextMiddleware, BaseHTTPMiddleware)
