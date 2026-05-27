"""
Health Check Endpoints
=======================
Provides three health check endpoints for different purposes:

/api/v1/health       → Detailed status for monitoring dashboards
/api/v1/health/live  → Kubernetes liveness probe (is the process alive?)
/api/v1/health/ready → Kubernetes readiness probe (ready for traffic?)

These endpoints are also used by:
  - AWS ECS health checks (decides if task is healthy)
  - Application Load Balancer (decides if instance gets traffic)
  - Docker Compose healthcheck directives
  - CloudWatch alarms (alert if health check fails)

Interview: "Our health endpoints follow the Kubernetes probe pattern.
/live returns 200 if the process responds. /ready returns 200 only if all
dependencies (DB, Redis) are reachable. This enables zero-downtime deployments —
the load balancer only sends traffic to ready instances."
"""

import time
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

# Track when the application started (for uptime calculation)
_startup_time = time.time()

router = APIRouter()


@router.get(
    "/live",
    summary="Liveness probe",
    description="Returns 200 if the application process is alive. Used by Kubernetes/ECS.",
)
async def liveness() -> JSONResponse:
    """
    Liveness probe — used by Kubernetes to know if the container should be restarted.

    This should ALWAYS return 200 if the process is responsive.
    Only returns non-200 if the process itself is fundamentally broken
    (e.g., deadlock, infinite loop consuming all CPU).

    It does NOT check database connectivity — that's the readiness probe's job.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "alive",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


@router.get(
    "/ready",
    summary="Readiness probe",
    description="Returns 200 only if all dependencies are reachable. Used by load balancers.",
)
async def readiness() -> JSONResponse:
    """
    Readiness probe — used by load balancers to know if traffic should be sent here.

    Checks:
    1. Database connectivity (can we execute a query?)
    2. Redis connectivity (optional — degraded mode if Redis is down)

    Returns 503 Service Unavailable if any critical dependency is down.
    The load balancer removes this instance from rotation until it's ready again.
    """
    checks: dict[str, dict] = {}
    is_ready = True

    # Check 1: Database
    try:
        from app.database import check_db_connection

        db_latency_ms = await check_db_connection()
        checks["database"] = {
            "status": "healthy",
            "latency_ms": db_latency_ms,
        }
    except Exception as e:
        is_ready = False
        checks["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        logger.error("health_check_db_failed", error=str(e))

    # Check 2: Redis (non-critical — app works without it, just slower)
    try:
        from app.cache import check_redis_connection

        redis_latency_ms = await check_redis_connection()
        checks["redis"] = {
            "status": "healthy",
            "latency_ms": redis_latency_ms,
        }
    except Exception as e:
        # Redis failure → warning, not error (app still works)
        checks["redis"] = {
            "status": "degraded",
            "error": str(e),
        }
        logger.warning("health_check_redis_failed", error=str(e))

    status_code = 200 if is_ready else 503
    overall_status = "ready" if is_ready else "not_ready"

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": checks,
        },
    )


@router.get(
    "",
    summary="Detailed health status",
    description="Returns comprehensive health information for monitoring dashboards.",
)
async def health_detail() -> JSONResponse:
    """
    Detailed health endpoint for monitoring dashboards and humans.

    Returns:
    - Application version and environment
    - Uptime
    - All dependency statuses with latencies
    - System information

    This is what you'd see in a Grafana dashboard or CloudWatch widget.
    """
    from app.config import get_settings

    settings = get_settings()

    uptime_seconds = time.time() - _startup_time

    # Run all checks
    dependency_checks: dict[str, dict] = {}

    # Database check
    try:
        from app.database import check_db_connection

        db_latency_ms = await check_db_connection()
        dependency_checks["database"] = {
            "status": "healthy",
            "type": "postgresql",
            "latency_ms": db_latency_ms,
            "host": (
                settings.database_url.split("@")[-1].split("/")[0]
                if "@" in settings.database_url
                else "localhost"
            ),
        }
    except Exception as e:
        dependency_checks["database"] = {
            "status": "unhealthy",
            "type": "postgresql",
            "error": str(e),
        }

    # Redis check
    try:
        from app.cache import check_redis_connection

        redis_latency_ms = await check_redis_connection()
        dependency_checks["redis"] = {
            "status": "healthy",
            "type": "redis",
            "latency_ms": redis_latency_ms,
        }
    except Exception as e:
        dependency_checks["redis"] = {
            "status": "degraded",
            "type": "redis",
            "error": str(e),
        }

    # Overall health: unhealthy if any CRITICAL dependency is down
    critical_deps = ["database"]
    overall_healthy = all(
        dependency_checks.get(dep, {}).get("status") == "healthy"
        for dep in critical_deps
    )

    return JSONResponse(
        status_code=200 if overall_healthy else 503,
        content={
            "status": "healthy" if overall_healthy else "degraded",
            "timestamp": datetime.now(UTC).isoformat(),
            "application": {
                "name": settings.app_name,
                "version": settings.app_version,
                "environment": settings.env,
                "debug": settings.debug,
                "uptime_seconds": round(uptime_seconds, 2),
                "uptime_human": _format_uptime(uptime_seconds),
            },
            "dependencies": dependency_checks,
        },
    )


def _format_uptime(seconds: float) -> str:
    """Convert seconds to human-readable uptime string."""
    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)
