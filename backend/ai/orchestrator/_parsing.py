"""Normalizes raw LLM JSON output to the canonical TradingSignal field names."""
import json
import logging

logger = logging.getLogger(__name__)


# ── Normaliser (shared) ────────────────────────────────────────────────────────

def _normalize_raw(raw: dict, *, timeframe: str, current_price: float) -> dict:
    """Map alternative LLM field names to the canonical TradingSignal schema."""
    out = dict(raw)

    if "action" not in out:
        for alias in ("signal", "side", "direction", "trade_action"):
            if alias in out:
                out["action"] = out.pop(alias)
                break

    if "rationale" not in out:
        for alias in ("explanation", "reason", "reasoning", "summary", "note"):
            if alias in out:
                out["rationale"] = out.pop(alias)
                break

    if "timeframe" not in out:
        out["timeframe"] = timeframe

    out.setdefault("action", "HOLD")
    out.setdefault("entry", current_price)
    out.setdefault("stop_loss", 0.0)
    out.setdefault("take_profit", 0.0)
    out.setdefault("confidence", 0.0)
    out.setdefault("rationale", "No rationale provided by model.")
    # Clamp expiry_multiplier to valid range; default 1.0 if absent or out-of-range
    raw_mult = out.get("expiry_multiplier", 1.0)
    try:
        out["expiry_multiplier"] = max(0.5, min(3.0, float(raw_mult)))
    except (TypeError, ValueError):
        out["expiry_multiplier"] = 1.0

    # LLM sometimes returns rationale as a nested dict — flatten to string
    if not isinstance(out.get("rationale"), str):
        val = out["rationale"]
        if isinstance(val, dict):
            out["rationale"] = json.dumps(val, ensure_ascii=False)
        else:
            out["rationale"] = str(val)

    if isinstance(out.get("action"), str):
        out["action"] = out["action"].upper()

    logger.debug("LLM raw → normalised: %s", out)
    return out

