"""
Custom Middleware
=================
Middleware is code that runs on EVERY request, before and after your handler.

Think of it as a pipeline:
  Request → Middleware1 → Middleware2 → Your Handler → Middleware2 → Middleware1 → Response

Our middleware stack:
  1. RequestIDMiddleware  → Assigns a unique ID to every request (for tracing)
  2. TimingMiddleware     → Measures how long each request takes
  3. (CORS is handled by FastAPI's built-in CORSMiddleware)
  4. (Rate limiting is handled by slowapi)

Why Request IDs?
  When a user reports "my expense didn't save at 3pm", you need to find
  THAT specific request in your logs. The request ID ties together:
  - The incoming request
  - Database queries made during the request
  - The response
  - Any errors

  You can tell the user: "What's your request ID?" → X-Request-ID: abc-123
  Then: CloudWatch filter { $.request_id = "abc-123" }

Interview: "Every request gets a unique UUID. It's added to response headers
as X-Request-ID and bound to all log entries during that request. This enables
end-to-end request tracing across our logs."
"""

import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique UUID to every incoming request.

    - Reads X-Request-ID header if client provides one (useful for distributed tracing)
    - Generates a new UUID if header is not present
    - Adds the request ID to:
        1. The request state (accessible in handlers)
        2. The response headers (client can see it)
        3. The structlog context (appears in ALL log entries for this request)
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Use client-provided request ID or generate a new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Store on request state — handlers can access via request.state.request_id
        request.state.request_id = request_id

        # Bind request_id to structlog context for this request
        # All log calls during this request will include request_id automatically
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
        finally:
            # Always clean up context vars (even on exceptions)
            structlog.contextvars.clear_contextvars()

        # Add request ID to response headers so clients can reference it
        response.headers["X-Request-ID"] = request_id
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """
    Measures and logs the duration of every request.

    Adds X-Process-Time header to responses.
    Logs slow requests (>1s) as warnings so you can identify performance problems.

    Production value: If your dashboard shows response times spiking at 3pm,
    you can search logs for slow_request events to find which endpoints are slow.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()  # High-precision timer

        response = await call_next(request)

        # Calculate duration in milliseconds
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Add timing to response headers
        response.headers["X-Process-Time"] = f"{duration_ms}ms"

        # Log the request
        log_data = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else "unknown",
        }

        # Log at appropriate level based on status code and duration
        if response.status_code >= 500:
            logger.error("request_failed", **log_data)
        elif response.status_code >= 400:
            logger.warning("request_error", **log_data)
        elif duration_ms > 1000:
            logger.warning("slow_request", **log_data)  # Warning for >1s responses
        else:
            logger.info("request_completed", **log_data)

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to every response.

    These headers instruct browsers to protect against common attacks:

    - Strict-Transport-Security (HSTS): "Always use HTTPS, never HTTP"
    - X-Content-Type-Options: "Don't guess content type (prevents MIME sniffing)"
    - X-Frame-Options: "Don't embed this in an iframe (prevents clickjacking)"
    - X-XSS-Protection: "Enable browser's XSS filter"
    - Referrer-Policy: "Don't leak URL in Referer header"

    Interview: "We add security headers to every response via middleware.
    This is one of the OWASP Top 10 security best practices."
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only add HSTS in production (HTTPS required)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response
