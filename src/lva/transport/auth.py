from __future__ import annotations

import hmac
import logging
from typing import Any, Callable
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..contracts.enums import ErrorCode
from ..contracts.errors import ErrorEnvelope

log = logging.getLogger("lva.transport.auth")

ALLOWED_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
}


class TokenValidator:
    def __init__(
        self,
        token: str | None = None,
        allowed_origins: set[str] | None = None,
        require_auth: bool = True,
    ) -> None:
        self.expected_token = token
        self.allowed_origins = allowed_origins or ALLOWED_ORIGINS
        self.require_auth = require_auth

    def set_token(self, token: str) -> None:
        self.expected_token = token
        self.require_auth = True

    def verify_token(self, token: str | None) -> bool:
        if not self.require_auth:
            # Explicit opt-out only; the shipped server never builds this.
            return True
        if not self.expected_token:
            # Fail closed (v1.2.1 PR-006): without a configured token nobody is
            # authenticated, so no client token may ever be accepted.
            return False
        if not token:
            return False
        return hmac.compare_digest(token.encode("utf-8"), self.expected_token.encode("utf-8"))

    def verify_origin(self, origin: str | None) -> bool:
        if not origin:
            # Native clients may omit Origin; the bearer token is still required.
            return True
        # Only the native bridge's fixed origins are allowed (v1.2.1 Phase 1):
        # a generic http://localhost or http://127.0.0.1 origin is not sufficient.
        return origin in self.allowed_origins


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, validator: TokenValidator) -> None:
        super().__init__(app)
        self.validator = validator

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Public health check endpoint is exempt
        if request.url.path in ("/health", "/api/health"):
            return await call_next(request)

        # Check Origin
        origin = request.headers.get("Origin")
        if not self.validator.verify_origin(origin):
            log.warning("Origin rejected: %s", origin)
            err = ErrorEnvelope(
                code=ErrorCode.ORIGIN_REJECTED,
                message=f"Origin '{origin}' is not permitted",
                severity="error",
                component="auth",
                correlation_id=uuid4(),
            )
            return JSONResponse(err.model_dump(mode="json"), status_code=403)

        # The bearer token travels only in the Authorization header: never in a
        # URL/query string, argv, env var, file or log (v1.2.1 PR-006).
        token: str | None = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        if self.validator.require_auth and not token:
            err = ErrorEnvelope(
                code=ErrorCode.AUTH_REQUIRED,
                message="Authorization bearer token required",
                severity="error",
                component="auth",
                correlation_id=uuid4(),
            )
            return JSONResponse(err.model_dump(mode="json"), status_code=401)

        if not self.validator.verify_token(token):
            err = ErrorEnvelope(
                code=ErrorCode.AUTH_FAILED,
                message="Invalid authorization token",
                severity="error",
                component="auth",
                correlation_id=uuid4(),
            )
            return JSONResponse(err.model_dump(mode="json"), status_code=403)

        return await call_next(request)
