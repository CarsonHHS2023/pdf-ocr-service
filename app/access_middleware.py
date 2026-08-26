"""ASGI middleware enforcing the temporary shared development access gate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

from app.access_security import (
    AccessConfigurationError,
    AccessTokenError,
    is_access_gate_enabled,
    verify_access_token,
)
from app.s0_upload_boundary_observability import (
    install_s0_upload_boundary_observability,
)
from app.s0_upload_durable_dispatch_compat import (
    install_s0_upload_durable_dispatch_compat,
)

# Exact-Staging gated and observational only. Install before app.main constructs
# the FastAPI application so the canonical upload request boundary includes
# multipart body receipt/parsing. Outside a tested Staging artifact these are no-ops.
install_s0_upload_boundary_observability()
install_s0_upload_durable_dispatch_compat()

_PUBLIC_EXACT_PATHS = {
    "/",
    "/api/access/login",
    "/api/v1/health",
    "/api/v1/health/config",
    "/api/v1/health/database-integrity",
    "/api/v1/health/database-backup",
    "/api/v1/health/database-recovery-cutover",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}
_PUBLIC_PREFIXES = ("/internal/",)


def is_public_access_path(path: str, method: str) -> bool:
    """Return whether a request bypasses the shared app access token gate."""
    if method.upper() == "OPTIONS":
        return True
    if path in _PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


class AppAccessGateMiddleware:
    """Require a valid Bearer token for application routes when enabled.

    Internal service/operator routes deliberately remain outside this gate and
    continue to use their existing independent authentication mechanisms.
    """

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET")
        if not is_access_gate_enabled() or is_public_access_path(path, method):
            await self.app(scope, receive, send)
            return

        authorization_values = [
            value.decode("latin-1")
            for key, value in scope.get("headers", [])
            if key.lower() == b"authorization"
        ]
        if len(authorization_values) != 1:
            await self._send_unauthorized(send)
            return

        scheme, separator, token = authorization_values[0].partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            await self._send_unauthorized(send)
            return

        try:
            verify_access_token(token.strip())
        except AccessConfigurationError:
            await self._send_unavailable(send)
            return
        except AccessTokenError:
            await self._send_unauthorized(send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_unauthorized(send: Any) -> None:
        response = JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response({"type": "http"}, None, send)

    @staticmethod
    async def _send_unavailable(send: Any) -> None:
        response = JSONResponse(
            {"detail": "Application access is not configured"},
            status_code=503,
        )
        await response({"type": "http"}, None, send)
