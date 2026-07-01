"""Pure validation helpers for LLM-suggested position MODIFY actions."""
from dataclasses import dataclass

_PIP_SIZE: dict[str, float] = {
    "XAUUSD": 0.1, "XAGUSD": 0.001,
}
_DEFAULT_PIP_SIZE = 0.0001  # standard forex pairs


def _get_pip_size(symbol: str) -> float:
    return _PIP_SIZE.get(symbol.upper(), _DEFAULT_PIP_SIZE)


@dataclass
class ConstraintResult:
    passed: bool
    reason: str | None = None


def validate_modify(
    *,
    direction: str,
    entry_price: float,
    current_price: float,
    current_sl: float,
    volume: float,
    balance: float,
    new_sl: float,
    new_tp: float,
    sl_pips: float,
    risk_pct: float,
    symbol: str,
) -> ConstraintResult:
    """Validate an LLM-suggested MODIFY against strategy risk constraints.

    Returns ConstraintResult(passed=True) if all checks pass, or
    ConstraintResult(passed=False, reason=...) with the first violated rule.
    """
    pip_size = _get_pip_size(symbol)

    # 1. Minimum SL distance from current price
    sl_distance = abs(current_price - new_sl)
    min_sl_distance = sl_pips * pip_size
    if sl_distance < min_sl_distance:
        return ConstraintResult(
            passed=False,
            reason=(
                f"new_sl too close: distance={sl_distance:.5f} < "
                f"min={min_sl_distance:.5f} ({sl_pips} pips)"
            ),
        )

    # 2. Trailing stop logic — SL may only move in favorable direction
    entry_to_current = (
        current_price - entry_price if direction == "BUY" else entry_price - current_price
    )
    if entry_to_current >= 0:  # position is at break-even or in profit
        if direction == "BUY" and new_sl < current_sl:
            return ConstraintResult(
                passed=False,
                reason=(
                    f"trailing stop violated: BUY position in profit, "
                    f"new_sl {new_sl} < current_sl {current_sl}"
                ),
            )
        if direction == "SELL" and new_sl > current_sl:
            return ConstraintResult(
                passed=False,
                reason=(
                    f"trailing stop violated: SELL position in profit, "
                    f"new_sl {new_sl} > current_sl {current_sl}"
                ),
            )

    # 3. Max risk per trade: new SL must not risk more than risk_pct of balance
    new_sl_distance_pips = abs(current_price - new_sl) / pip_size
    approx_pip_value = 10.0  # USD per pip per standard lot (approximate)
    max_risk_usd = balance * risk_pct
    actual_risk_usd = new_sl_distance_pips * approx_pip_value * volume
    if actual_risk_usd > max_risk_usd * 1.2:  # 20% tolerance
        return ConstraintResult(
            passed=False,
            reason=(
                f"max risk exceeded: risk={actual_risk_usd:.2f} USD > "
                f"max={max_risk_usd:.2f} USD ({risk_pct * 100:.1f}% of {balance:.2f})"
            ),
        )

    # 4. Minimum R:R — new_tp must be at least 1:1 from entry vs new_sl
    sl_dist = abs(entry_price - new_sl)
    if direction == "BUY":
        tp_dist = abs(new_tp - entry_price)
    else:
        tp_dist = abs(entry_price - new_tp)

    if sl_dist > 0 and tp_dist < sl_dist:
        return ConstraintResult(
            passed=False,
            reason=(
                f"R:R below 1:1: TP distance {tp_dist:.5f} < SL distance {sl_dist:.5f}"
            ),
        )

    return ConstraintResult(passed=True)
