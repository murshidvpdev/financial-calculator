"""
Redis Cache Module
==================
Manages the Redis connection pool for caching, sessions, and rate limiting.

Why Redis?
  PostgreSQL is great for persistent data but has ~1-5ms query latency.
  Redis is in-memory → <1ms latency. For frequently accessed data,
  cache it in Redis first, fall back to DB if cache miss.

Cache-Aside Pattern (what we use):
  1. Request comes in
  2. Check Redis: if data exists → return it (cache hit, fast!)
  3. If not in Redis → query PostgreSQL (cache miss, slower)
  4. Store result in Redis with TTL → next request is fast

  User requests dashboard data
       │
       ▼
  Redis: key="dashboard:user123"?
       │         │
    HIT ✓     MISS ✗
       │         │
       ▼         ▼
  Return     Query PostgreSQL
  cached     → Store in Redis (TTL=1h)
  data       → Return data

Use cases in Finance Calculator:
  - Dashboard analytics (cache for 1 hour)
  - Exchange rates (cache for 30 minutes)
  - JWT token blacklist (when users logout)
  - Rate limiting counters (requests per minute)
  - User session data

Interview: "We use Redis as a cache-aside cache. Expensive analytics queries
are cached with a TTL. When data changes (new expense added), we invalidate
the relevant cache keys. JWT tokens are blacklisted in Redis on logout."
"""

import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Module-level Redis client (initialized during startup)
_redis_client: Any | None = None


async def init_redis() -> None:
    """Initialize the Redis connection pool. Called at application startup."""
    global _redis_client

    from app.config import get_settings

    settings = get_settings()

    # Import here to avoid import errors if redis is not installed
    from redis.asyncio import from_url

    _redis_client = await from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,  # Return strings, not bytes
        max_connections=20,  # Connection pool size
    )

    # Verify connection
    await _redis_client.ping()
    logger.info("redis_pool_initialized")


async def close_redis() -> None:
    """Close the Redis connection pool. Called at application shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("redis_pool_closed")


async def check_redis_connection() -> float:
    """Check Redis connectivity and return latency in milliseconds."""
    if not _redis_client:
        raise RuntimeError("Redis not initialized")

    start = time.perf_counter()
    await _redis_client.ping()
    return round((time.perf_counter() - start) * 1000, 2)


def get_redis() -> Any:
    """
    Get the Redis client instance.
    Used as a FastAPI dependency or called directly from services.
    """
    if not _redis_client:
        raise RuntimeError("Redis not initialized")
    return _redis_client


async def cache_get(key: str) -> str | None:
    """Get a value from cache. Returns None on cache miss or Redis unavailable."""
    try:
        if not _redis_client:
            return None
        return await _redis_client.get(key)  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning("cache_get_failed", key=key, error=str(e))
        return None


async def cache_set(key: str, value: str, ttl_seconds: int = 3600) -> bool:
    """
    Set a value in cache with TTL (Time To Live).
    TTL ensures cache entries expire automatically (no stale data forever).
    Returns True on success, False if Redis is unavailable.
    """
    try:
        if not _redis_client:
            return False
        await _redis_client.setex(key, ttl_seconds, value)
        return True
    except Exception as e:
        logger.warning("cache_set_failed", key=key, error=str(e))
        return False


async def cache_delete(key: str) -> bool:
    """Delete a key from cache (cache invalidation). Returns True on success."""
    try:
        if not _redis_client:
            return False
        await _redis_client.delete(key)
        return True
    except Exception as e:
        logger.warning("cache_delete_failed", key=key, error=str(e))
        return False


async def cache_delete_pattern(pattern: str) -> int:
    """
    Delete all keys matching a pattern.
    Example: cache_delete_pattern("dashboard:user123:*")
    Returns the number of keys deleted.
    """
    try:
        if not _redis_client:
            return 0
        keys = await _redis_client.keys(pattern)
        if keys:
            return await _redis_client.delete(*keys)  # type: ignore[no-any-return]
        return 0
    except Exception as e:
        logger.warning("cache_delete_pattern_failed", pattern=pattern, error=str(e))
        return 0
