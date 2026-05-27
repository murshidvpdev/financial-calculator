"""
Custom Exceptions and Exception Handlers
=========================================
Defines the exception hierarchy for the Finance Calculator.

Why custom exceptions?
  1. Semantics: raise ExpenseNotFoundError() is clearer than raise HTTPException(404)
  2. Consistency: ALL 404 errors look the same to API consumers
  3. Decoupling: business logic raises domain exceptions, not HTTP exceptions
  4. Testability: tests catch specific exceptions, not generic HTTP status codes

Architecture:
  Business Logic:
    raise ExpenseNotFoundError(expense_id="uuid-123")
                    ↓
  Exception Handler (registered with FastAPI):
    Returns: {"error": "NOT_FOUND", "message": "Expense uuid-123 not found", "request_id": "..."}

Error Response Format (consistent across all endpoints):
  {
    "error": "ERROR_CODE",          ← Machine-readable code (for client error handling)
    "message": "Human message",    ← Human-readable explanation
    "details": {...},               ← Optional extra context
    "request_id": "uuid-..."        ← For support/debugging
  }

Interview: "We have a custom exception hierarchy. Business logic raises
domain exceptions. FastAPI exception handlers convert these to consistent
JSON error responses. Clients can rely on the error code format."
"""

import structlog
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


# =============================================================================
# BASE EXCEPTION
# =============================================================================
class FinanceAppError(Exception):
    """
    Base exception for all Finance Calculator errors.
    All custom exceptions should inherit from this.

    Having a base exception lets you do:
        try:
            ...
        except FinanceAppError as e:
            # Handle any app-specific error
    """

    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


# =============================================================================
# HTTP EXCEPTIONS (mapped to HTTP status codes)
# =============================================================================
class NotFoundError(FinanceAppError):
    """Resource does not exist (HTTP 404)."""

    def __init__(self, resource: str, resource_id: str | None = None) -> None:
        message = f"{resource} not found"
        if resource_id:
            message = f"{resource} with id '{resource_id}' not found"
        super().__init__(
            message=message,
            error_code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class UnauthorizedError(FinanceAppError):
    """Not authenticated (HTTP 401)."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(
            message=message,
            error_code="UNAUTHORIZED",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ForbiddenError(FinanceAppError):
    """Authenticated but not authorized (HTTP 403)."""

    def __init__(
        self, message: str = "You don't have permission to perform this action"
    ) -> None:
        super().__init__(
            message=message,
            error_code="FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ConflictError(FinanceAppError):
    """Resource already exists or state conflict (HTTP 409)."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            message=message,
            error_code="CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class ValidationError(FinanceAppError):
    """Business rule validation failed (HTTP 422)."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class RateLimitError(FinanceAppError):
    """Too many requests (HTTP 429)."""

    def __init__(self, message: str = "Too many requests. Please slow down.") -> None:
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


# =============================================================================
# DOMAIN EXCEPTIONS (Business Logic Level)
# =============================================================================
class UserNotFoundError(NotFoundError):
    def __init__(self, user_id: str | None = None) -> None:
        super().__init__(resource="User", resource_id=user_id)


class ExpenseNotFoundError(NotFoundError):
    def __init__(self, expense_id: str | None = None) -> None:
        super().__init__(resource="Expense", resource_id=expense_id)


class CategoryNotFoundError(NotFoundError):
    def __init__(self, category_id: str | None = None) -> None:
        super().__init__(resource="Category", resource_id=category_id)


class BudgetNotFoundError(NotFoundError):
    def __init__(self, budget_id: str | None = None) -> None:
        super().__init__(resource="Budget", resource_id=budget_id)


class EmailAlreadyExistsError(ConflictError):
    def __init__(self, email: str) -> None:
        super().__init__(
            message=f"An account with email '{email}' already exists",
            details={"email": email},
        )


class InvalidCredentialsError(UnauthorizedError):
    def __init__(self) -> None:
        super().__init__(message="Invalid email or password")


class InvalidTokenError(UnauthorizedError):
    def __init__(self) -> None:
        super().__init__(message="Invalid or expired token")


class InsufficientFundsError(ValidationError):
    def __init__(self, available: float, required: float) -> None:
        super().__init__(
            message=f"Insufficient funds: available ${available:.2f}, required ${required:.2f}",
            details={"available": available, "required": required},
        )


# =============================================================================
# EXCEPTION HANDLERS (registered with FastAPI)
# =============================================================================
def get_request_id(request: Request) -> str:
    """Extract request ID from request state (set by RequestIDMiddleware)."""
    return getattr(request.state, "request_id", "unknown")


async def finance_app_exception_handler(
    request: Request, exc: FinanceAppError
) -> JSONResponse:
    """
    Handle all custom FinanceAppError exceptions.

    Converts domain exceptions to consistent JSON responses.
    Logs appropriately based on severity.
    """
    request_id = get_request_id(request)

    # Log errors (but not 4xx client errors at error level — they're normal)
    if exc.status_code >= 500:
        logger.error(
            "server_error",
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            request_id=request_id,
            exc_info=True,
        )
    elif exc.status_code >= 400:
        logger.warning(
            "client_error",
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            request_id=request_id,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "request_id": request_id,
        },
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handle standard HTTP exceptions (raised by FastAPI internally).
    Converts them to our consistent error format.
    """
    request_id = get_request_id(request)

    # Map HTTP status codes to error codes
    error_code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        408: "REQUEST_TIMEOUT",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }

    error_code = error_code_map.get(exc.status_code, "HTTP_ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_code,
            "message": str(exc.detail),
            "details": {},
            "request_id": request_id,
        },
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors (when request body is malformed).

    FastAPI raises RequestValidationError when the request doesn't match the schema.
    Example: endpoint expects {"amount": float} but client sends {"amount": "abc"}

    We format the validation errors to be useful for API consumers.
    """
    request_id = get_request_id(request)

    # Format Pydantic validation errors into a readable structure
    formatted_errors = []
    for error in exc.errors():
        # 'loc' is a tuple like ('body', 'amount') indicating where the error is
        field_path = " → ".join(str(loc) for loc in error["loc"] if loc != "body")
        formatted_errors.append(
            {
                "field": field_path or "body",
                "message": error["msg"],
                "type": error["type"],
            }
        )

    logger.warning(
        "validation_error",
        errors=formatted_errors,
        request_id=request_id,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": {"errors": formatted_errors},
            "request_id": request_id,
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for any unhandled exceptions.

    In production: returns a generic error (don't leak stack traces!)
    Always logs the full exception for debugging.
    """
    request_id = get_request_id(request)

    logger.error(
        "unhandled_exception",
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        request_id=request_id,
        exc_info=True,  # Include full stack trace in logs
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            # NEVER expose internal error details to clients in production!
            "message": "An unexpected error occurred. Please try again.",
            "details": {},
            "request_id": request_id,
        },
    )
