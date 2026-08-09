"""Origin enforcement for state-changing endpoints authenticated by browser cookies."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin use of refresh cookies; bearer-token APIs are unaffected."""

    def __init__(self, app: object, allowed_origins: set[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.allowed_origins = allowed_origins

    async def dispatch(self, request: Request, call_next: object) -> Response:
        cookie_authenticated = "jat_refresh_token" in request.cookies
        protected = request.url.path.endswith("/auth/refresh") or request.url.path.endswith(
            "/auth/logout"
        )
        if (
            cookie_authenticated
            and protected
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            origin = request.headers.get("origin")
            if origin not in self.allowed_origins:
                return JSONResponse(
                    status_code=403,
                    content={
                        "type": "https://jat.ai/problems/csrf-rejected",
                        "title": "Cross-site request rejected",
                        "status": 403,
                    },
                )
        return await call_next(request)  # type: ignore[operator]
