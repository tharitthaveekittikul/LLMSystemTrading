"""LLM pricing table — cost per 1M tokens, USD.

Last verified: 2026-03-06.
Update this file when provider pricing changes.
Source: provider pricing pages (no public API for pricing).
"""

# Prices are per 1,000,000 tokens in USD (Updated: March 2026).
LLM_PRICING: dict[str, dict[str, float]] = {
    # Google Gemini (Standard pricing for prompts <= 200k)
    # Note: Prices double for context > 200k.
    "gemini-2.5-pro":            {"input": 1.25,   "output": 10.00},
    "gemini-2.5-flash":          {"input": 0.30,   "output": 2.50},
    "gemini-2.5-flash-lite":     {"input": 0.10,   "output": 0.40},
    "gemini-3-flash-preview":    {"input": 0.50,   "output": 3.00},

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
    pricing = LLM_PRICING.get(model)
    if pricing is None:
        return None
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 8)


def get_pricing_list() -> list[dict]:
    """Return list of {model, provider, input_per_1m_usd, output_per_1m_usd} for API responses."""
    provider_map = {
        "google": ["gemini-2.5-flash", "gemini-2.5-flash-image", "gemini-2.0-flash",
                   "gemini-1.5-pro", "gemini-1.5-flash"],
        "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    }
    result = []
    for provider, models in provider_map.items():
        for model in models:
            p = LLM_PRICING.get(model, {})
            result.append({
                "model": model,
                "provider": provider,
                "input_per_1m_usd": p.get("input"),
                "output_per_1m_usd": p.get("output"),
            })
    return result
