"""Shared LLM confidence-bucket thresholds.

Used by both the RAG context builder (services/rag_context.py) and the
learning-analytics routes (api/routes/llm_analytics.py) to bucket a
signal's confidence score into the same very_high/high/medium/low bands.
"""

CONFIDENCE_VERY_HIGH = 0.80
CONFIDENCE_HIGH = 0.65
CONFIDENCE_MEDIUM = 0.50


def confidence_bucket(confidence: float | None) -> str:
    """Map a 0.0-1.0 confidence score to a bucket key."""
    if confidence is None:
        return "unknown"
    if confidence >= CONFIDENCE_VERY_HIGH:
        return "very_high"
    if confidence >= CONFIDENCE_HIGH:
        return "high"
    if confidence >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"
