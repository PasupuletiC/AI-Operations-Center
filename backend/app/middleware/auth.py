"""
API Key Auth Middleware — simple Bearer token guard for the /api routes.

Set DASHBOARD_API_KEY in your .env to enable protection.
If the key is not set, auth is bypassed (dev mode).
"""
import os
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Paths that are always public (no key required)
PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = os.getenv("DASHBOARD_API_KEY", "")

        # Dev mode: no key configured → allow everything
        if not api_key or api_key.startswith("your_"):
            return await call_next(request)

        # Public paths always allowed
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Check Authorization: Bearer <key>  OR  X-API-Key: <key>
        auth_header = request.headers.get("Authorization", "")
        x_key = request.headers.get("X-API-Key", "")

        provided = ""
        if auth_header.startswith("Bearer "):
            provided = auth_header[len("Bearer "):]
        elif x_key:
            provided = x_key

        if provided != api_key:
            logger.warning(f"[Auth] Rejected request to {request.url.path} — invalid API key")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Set X-API-Key header."},
            )

        return await call_next(request)
