"""Position sizing — risk-based lot size calculation.

Formula:
    risk_amount  = balance × risk_pct
    sl_value_per_lot = abs(fill_price - sl_price) × contract_size
    lot_size     = risk_amount / sl_value_per_lot

Example — XAUUSD at $1,800, SL $1.50 away, $1,000 balance, 1% risk:
    risk_amount  = $10
    sl_value     = 1.50 × 100 = $150 per lot
    lot_size     = 10 / 150 ≈ 0.07 lots
"""
from __future__ import annotations


def calc_lot_size(
    balance: float,
    risk_pct: float,
    fill_price: float,
    sl_price: float,
    contract_size: float,
    *,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
) -> float:
    """Return lot size that risks exactly risk_pct of balance on this trade.

    Args:
        balance:       Current account balance / equity in account currency.
        risk_pct:      Fraction of balance to risk (e.g. 0.01 = 1 %).
        fill_price:    Actual entry fill price.
        sl_price:      Stop-loss price level.
        contract_size: Units per standard lot for this symbol (from _contract_size).
        min_lot:       Minimum lot size allowed (default 0.01).
        max_lot:       Maximum lot size cap (default 100.0).

    Returns:
        Lot size rounded to 2 decimal places, clamped to [min_lot, max_lot].
    """
    sl_distance = abs(fill_price - sl_price)
    if sl_distance < 1e-8:
        return min_lot

    risk_amount = balance * risk_pct
    sl_value_per_lot = sl_distance * contract_size
    lot_size = risk_amount / sl_value_per_lot
    lot_size = round(lot_size, 2)
    return max(min_lot, min(lot_size, max_lot))
