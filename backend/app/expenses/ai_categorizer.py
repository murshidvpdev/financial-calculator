"""
AI Expense Categorizer — Phase 17
===================================
Uses Claude API to intelligently categorize expenses based on description.

Why AI categorization?
  Rule-based matching (keywords → category) breaks on edge cases:
    "IRCTC" → Travel? Food? (it's train tickets → Travel)
    "ZOMATO" → Food (obvious)
    "APL*APPLE" → Shopping? Electronics? Subscriptions?

  Claude understands context and merchant names globally.
  It returns consistent JSON we can map to our category system.

Cache strategy:
  Same description → same category 99% of the time.
  Cache AI responses in Redis for 7 days (key = normalized description).
  Saves API cost + latency for repeated transactions (same merchant).

Cost estimate:
  Claude Haiku: ~$0.25 per million input tokens
  Average description: ~10 tokens
  1000 categorizations: ~$0.003 (less than 1 cent)

Usage:
  Called from import_service.py after parsing transactions.
  Falls back gracefully if API key not set or API call fails.
"""

from __future__ import annotations

import hashlib
import json

import structlog

from app.cache import cache_get, cache_set

logger = structlog.get_logger(__name__)

_CACHE_TTL = 7 * 24 * 3600  # 7 days — merchant names don't change


def _cache_key(description: str) -> str:
    """Stable cache key from description — normalize and hash."""
    normalized = description.lower().strip()[:100]
    return f"ai_category:{hashlib.md5(normalized.encode()).hexdigest()}"  # noqa: S324


_SYSTEM_PROMPT = """You are an expense categorizer for an Indian personal finance app.
Given a transaction description, return the best matching category.

Available categories (use EXACTLY one of these names):
- Food & Dining (restaurants, food delivery, cafes, groceries)
- Transportation (fuel, Uber, Ola, auto, bus, train, IRCTC, flight)
- Shopping (clothes, Amazon, Flipkart, electronics, gifts)
- Entertainment (movies, OTT subscriptions, Netflix, Spotify, games)
- Healthcare (pharmacy, hospital, doctor, medicines)
- Utilities (electricity, water, internet, phone recharge, DTH)
- Education (courses, books, school fees, Udemy, Coursera)
- Travel (hotels, holiday packages, tourism)
- Personal Care (salon, spa, gym, fitness)
- Transfer (money transfer, UPI to person, wallet top-up)
- Other (anything that doesn't clearly fit above)

Respond with ONLY a JSON object, no explanation:
{"category": "<category name>", "confidence": <0.0-1.0>}"""


async def categorize_expense(description: str) -> str | None:
    """
    Use Claude to categorize an expense description.

    Returns the category name string, or None if categorization fails.
    Uses Redis cache to avoid repeated API calls for same merchant.

    Args:
        description: Raw transaction description (e.g. "ZOMATO*ORDER 12345")

    Returns:
        Category name (e.g. "Food & Dining") or None on failure
    """
    if not description or len(description.strip()) < 3:
        return None

    # Check cache first
    key = _cache_key(description)
    cached = await cache_get(key)
    if cached:
        logger.debug("ai_category_cache_hit", description=description[:50])
        return cached

    try:
        import anthropic

        from app.config import get_settings

        settings = get_settings()

        # Skip if no API key configured
        if not getattr(settings, "anthropic_api_key", None):
            return None

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fastest + cheapest for simple classification
            max_tokens=64,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Transaction: {description[:200]}"}],
        )

        raw = message.content[0].text.strip()
        data = json.loads(raw)
        category = data.get("category", "Other")
        confidence = float(data.get("confidence", 0))

        # Only trust high-confidence results
        if confidence < 0.6:
            category = "Other"

        # Cache the result
        await cache_set(key, category, _CACHE_TTL)

        logger.info(
            "ai_categorized",
            description=description[:50],
            category=category,
            confidence=confidence,
        )
        return category

    except Exception as e:
        logger.warning(
            "ai_categorization_failed", error=str(e), description=description[:50]
        )
        return None


async def categorize_batch(descriptions: list[str]) -> list[str | None]:
    """
    Categorize multiple descriptions efficiently.
    Checks cache first for each, only calls API for cache misses.
    """
    results: list[str | None] = []
    for desc in descriptions:
        category = await categorize_expense(desc)
        results.append(category)
    return results
