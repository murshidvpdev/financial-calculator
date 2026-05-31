"""
Custom Middleware — Pure ASGI Implementation
=============================================
Middleware is code that runs on EVERY request, before and after your handler.

Think of it as a pipeline:
  Request → Middleware1 → Middleware2 → Your Handler → Middleware2 → Middleware1 → Response

Our middleware stack:
  1. RequestIDMiddleware    → Assigns a unique ID to every request (for tracing)
  2. RequestTimingMiddleware → Measures how long each request takes
  3. SecurityHeadersMiddleware → Adds security headers to every response
  4. (CORS is handled by FastAPI's built-in CORSMiddleware)

Why Pure ASGI instead of BaseHTTPMiddleware?
  Starlette's BaseHTTPMiddleware uses a thread-based call_next implementation
  that can cause "Future attached to a different loop" errors when combined
  with asyncpg (pure asyncio DB driver) and anyio in tests.

  Pure ASGI middleware (implementing __call__ directly) avoids this entirely:
  - No hidden thread pools
  - No asyncio task context switches
  - Compatible with asyncpg in all test setups
  - Better performance (no overhead of BaseHTTPMiddleware's streaming proxy)

Pure ASGI middleware pattern:
  class MyMiddleware:
      def __init__(self, app):
          self.app = app

      async def __call__(self, scope, receive, send):
          # scope: connection info (type, path, headers, etc.)
          # receive: async callable to read the request body
          # send: async callable to write the response
          if scope["type"] == "http":
              # Modify send to intercept/modify responses
              async def modified_send(message):
                  if message["type"] == "http.response.start":
                      # Add/modify headers here
                      ...
                  await send(message)
              await self.app(scope, receive, modified_send)
          else:
              # Pass through WebSocket, lifespan, etc.
              await self.app(scope, receive, send)

Interview: "We use pure ASGI middleware instead of Starlette's BaseHTTPMiddleware.
Pure ASGI gives us lower-level control, better performance, and avoids asyncio
event loop issues that arise when BaseHTTPMiddleware wraps asyncpg-based apps."
"""

import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger(__name__)


# =============================================================================
# 1. REQUEST ID MIDDLEWARE
# =============================================================================


class RequestIDMiddleware:
    """
    Assigns a unique UUID to every incoming request.

    - Reads X-Request-ID header if client provides one (distributed tracing)
    - Generates a new UUID if header is not present
    - Adds the request ID to:
        1. scope["state"] (accessible in handlers via request.state.request_id)
        2. The response headers (client can see it)
        3. The structlog context (appears in ALL log entries for this request)

    Why request IDs?
      When a user reports "my expense didn't save at 3pm", you need to find
      THAT specific request in your logs. Request ID ties together all log
      entries for a single request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            # Pass through lifespan events without modification
            await self.app(scope, receive, send)
            return

        # Extract or generate request ID
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())

        # Store on scope state so handlers can access via request.state.request_id
        if "state" not in scope:
            scope["state"] = {}  # type: ignore[typeddict-item]
        scope["state"]["request_id"] = request_id  # type: ignore[index]

        # Bind to structlog context — all log calls during this request include request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                # Inject X-Request-ID into response headers
                headers_obj = MutableHeaders(scope=message)
                headers_obj.append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # Always clean up structlog context (even on exceptions)
            structlog.contextvars.clear_contextvars()


# =============================================================================
# 2. REQUEST TIMING MIDDLEWARE
# =============================================================================


class RequestTimingMiddleware:
    """
    Measures and logs the duration of every request.

    Adds X-Process-Time header to responses.
    Logs slow requests (>1s) as warnings.

    Production value: If your dashboard shows response times spiking at 3pm,
    search logs for slow_request events to find which endpoints are slow.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        status_code = 200  # Default, updated when response starts

        async def send_with_timing(message: dict) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

                # Add timing header
                headers_obj = MutableHeaders(scope=message)
                headers_obj.append("X-Process-Time", f"{duration_ms}ms")

                # Log the request
                # Extract path and method from scope
                path = scope.get("path", "/")
                method = scope.get("method", "?")
                client = scope.get("client")
                client_ip = client[0] if client else "unknown"

                log_data = {
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                }

                if status_code >= 500:
                    logger.error("request_failed", **log_data)
                elif status_code >= 400:
                    logger.warning("request_error", **log_data)
                elif duration_ms > 1000:
                    logger.warning("slow_request", **log_data)
                else:
                    logger.info("request_completed", **log_data)

            await send(message)

        await self.app(scope, receive, send_with_timing)


# =============================================================================
# 3. SECURITY HEADERS MIDDLEWARE
# =============================================================================


class SecurityHeadersMiddleware:
    """
    Adds security headers to every HTTP response.

    These headers instruct browsers to protect against common attacks:

    - X-Content-Type-Options: "Don't guess content type (prevents MIME sniffing)"
    - X-Frame-Options: "Don't embed this in an iframe (prevents clickjacking)"
    - X-XSS-Protection: "Enable browser's XSS filter"
    - Referrer-Policy: "Don't leak URL in Referer header"
    - Permissions-Policy: Disable unnecessary browser features

    Interview: "We add security headers to every response via middleware.
    This is one of the OWASP Top 10 security best practices. We use pure ASGI
    middleware for reliability and performance."
    """

    _SECURITY_HEADERS = [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("X-XSS-Protection", "1; mode=block"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
        # HSTS: tell browsers to ONLY use HTTPS for 1 year (production must be HTTPS)
        ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
        # CSP: restrict where scripts/styles/images can load from (prevents XSS)
        (
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
            "font-src 'self' fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'",
        ),
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers_obj = MutableHeaders(scope=message)
                for header_name, header_value in self._SECURITY_HEADERS:
                    headers_obj.append(header_name, header_value)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
