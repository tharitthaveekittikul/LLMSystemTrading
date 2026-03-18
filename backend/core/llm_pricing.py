"""LLM pricing table — cost per 1M tokens, USD.

Last verified: 2026-03-06.
Update this file when provider pricing changes.
Source: provider pricing pages (no public API for pricing).
OpenRouter pricing is fetched live from https://openrouter.ai/api/v1/models (1h cache).
"""
import logging
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# OpenRouter pricing cache (1h TTL)
_or_cache: dict[str, dict[str, float]] = {}
_or_cache_time: datetime | None = None
_OR_TTL = timedelta(hours=1)

# Prices are per 1,000,000 tokens in USD (Updated: March 2026).
LLM_PRICING: dict[str, dict[str, float]] = {
    # Google Gemini (Standard pricing for prompts <= 200k)
    # Note: Prices double for context > 200k.
    "gemini-2.0-flash":                          {"input": 0.10,   "output": 0.40},
    "gemini-2.0-flash-001":                      {"input": 0.15,   "output": 0.60},
    "gemini-2.0-flash-lite":                     {"input": 0.075,  "output": 0.30},
    "gemini-2.0-flash-lite-001":                 {"input": 0.075,  "output": 0.30},
    "gemini-2.5-computer-use-preview-10-2025":   {"input": 1.25,   "output": 10.00},
    "gemini-2.5-flash":                          {"input": 0.30,   "output": 2.50},
    "gemini-2.5-flash-image":                    {"input": 0.30,   "output": 2.50},
    "gemini-2.5-flash-lite":                     {"input": 0.10,   "output": 0.40},
    "gemini-2.5-flash-lite-preview-09-2025":     {"input": 0.10,   "output": 0.40},
    "gemini-2.5-flash-native-audio-latest":      {"input": 0.30,   "output": 2.50},
    "gemini-2.5-flash-native-audio-preview-09-2025": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-native-audio-preview-12-2025": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-preview-tts":              {"input": 0.30,   "output": 2.50},
    "gemini-2.5-pro":                            {"input": 1.25,   "output": 10.00},
    "gemini-2.5-pro-preview-tts":                {"input": 1.25,   "output": 10.00},
    "gemini-3-flash-preview":                    {"input": 0.50,   "output": 3.00},
    "gemini-3-pro-image-preview":                {"input": 2.00,   "output": 12.00},
    "gemini-3-pro-preview":                      {"input": 2.00,   "output": 12.00},
    "gemini-3.1-flash-image-preview":            {"input": 0.25,   "output": 1.50},
    "gemini-3.1-flash-lite-preview":             {"input": 0.25,   "output": 1.50},
    "gemini-3.1-pro-preview":                    {"input": 2.00,   "output": 12.00},
    "gemini-3.1-pro-preview-customtools":        {"input": 2.00,   "output": 12.00},
    "gemini-embedding-001":                      {"input": 0.10,   "output": 0.00},
    "gemini-embedding-2-preview":                {"input": 0.15,   "output": 0.00},
    "gemini-flash-latest":                       {"input": 0.30,   "output": 2.50},
    "gemini-flash-lite-latest":                  {"input": 0.10,   "output": 0.40},
    "gemini-pro-latest":                         {"input": 1.25,   "output": 10.00},
    "gemini-robotics-er-1.5-preview":            {"input": 0.30,   "output": 2.50},

    # Anthropic Claude (Standard pricing for prompts <= 200k)
    # Note: Prices increase/double for context > 200k.
    "claude-opus-4-6":           {"input": 5.00,   "output": 25.00},
    "claude-sonnet-4-6":         {"input": 3.00,   "output": 15.00},
    "claude-haiku-4-5":          {"input": 1.00,   "output": 5.00},

    # OpenAI (Standard tier)
    "gpt-5.2":                   {"input": 1.75,   "output": 14.00},
    "gpt-5-mini":                {"input": 0.25,   "output": 2.00},
    "gpt-4o":                    {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":               {"input": 0.15,   "output": 0.60},
    "o3":                        {"input": 2.00,   "output": 8.00},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return estimated cost in USD. Returns None if model is unknown."""
    pricing = LLM_PRICING.get(model) or _or_cache.get(model)
    if pricing is None:
        return None
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 8)


async def fetch_openrouter_pricing() -> dict[str, dict[str, float]]:
    """Fetch model pricing from OpenRouter API.

    Returns {model_id: {input, output}} with prices per 1M tokens in USD.
    Results are cached for 1 hour; stale cache is returned on error.
    """
    global _or_cache, _or_cache_time
    now = datetime.now(UTC)
    if _or_cache and _or_cache_time and (now - _or_cache_time) < _OR_TTL:
        return _or_cache

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            resp.raise_for_status()
            data = resp.json()

        result: dict[str, dict[str, float]] = {}
        for m in data.get("data", []):
            model_id = m.get("id", "")
            pricing = m.get("pricing", {})
            try:
                inp = float(pricing.get("prompt", 0)) * 1_000_000
                out = float(pricing.get("completion", 0)) * 1_000_000
                result[model_id] = {"input": round(inp, 4), "output": round(out, 4)}
            except (ValueError, TypeError):
                pass

        _or_cache = result
        _or_cache_time = now
        logger.debug("OpenRouter pricing fetched: %d models", len(result))
        return result

    except Exception as exc:
        logger.warning("Failed to fetch OpenRouter pricing: %s — using stale cache", exc)
        return _or_cache


def get_pricing_list(
    active_models: list[tuple[str, str]],
    openrouter_prices: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    """Return pricing only for actively configured models.

    Args:
        active_models: list of (provider, model_name) tuples from DB assignments.
        openrouter_prices: pre-fetched OpenRouter pricing (from fetch_openrouter_pricing()).
    """
    seen: set[tuple[str, str]] = set()
    result = []
    for provider, model_name in active_models:
        key = (provider, model_name)
        if key in seen or not model_name:
            continue
        seen.add(key)

        p = LLM_PRICING.get(model_name)
        if p is None and provider == "openrouter" and openrouter_prices:
            p = openrouter_prices.get(model_name)

        result.append({
            "model": model_name,
            "provider": provider,
            "input_per_1m_usd": p["input"] if p else None,
            "output_per_1m_usd": p["output"] if p else None,
        })
    return result
