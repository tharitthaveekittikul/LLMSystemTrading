"""Backtest analytics aggregation service.

Computes grouped statistics, heatmap matrices, and recommendations
from a list of BacktestTrade dicts (or ORM objects).
"""
from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def aggregate_by_group(trades: list[dict], group_by: str) -> list[dict]:
    """Group trades by a field and compute per-group stats.

    Args:
        trades:   List of trade dicts with keys: symbol, pattern_name, profit, direction.
        group_by: Field name to group by (e.g. "pattern_name" or "symbol").

    Returns:
        List of group stats dicts, sorted by total_pnl descending.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = t.get(group_by) or "Unknown"
        groups[key].append(t)

    result = []
    for name, group_trades in groups.items():
        profits = [t.get("profit") or 0.0 for t in group_trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        win_rate = len(wins) / len(profits) if profits else 0.0
        total_pnl = sum(profits)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        total_win = sum(wins)
        total_loss = abs(sum(losses))
        profit_factor = total_win / total_loss if total_loss > 0 else float("inf")

        # Best symbol for this group
        symbol_pnl: dict[str, float] = defaultdict(float)
        for t in group_trades:
            symbol_pnl[t.get("symbol", "??")] += t.get("profit") or 0.0
        best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else "??"

        result.append({
            "name": name,
            "trades": len(group_trades),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
            "best_symbol": best_symbol,
        })

    result.sort(key=lambda g: g["total_pnl"], reverse=True)
    return result


def build_heatmap(
    trades: list[dict],
    axis1: str,
    axis2: str,
    metric: str = "win_rate",
) -> dict:
    """Build a 2D heatmap matrix.

    Args:
        trades: List of trade dicts.
        axis1:  Row axis field (e.g. "symbol").
        axis2:  Column axis field (e.g. "pattern_name").
        metric: Metric to display ("win_rate", "total_pnl", "profit_factor").

    Returns:
        { labels_x: [str], labels_y: [str], values: float[][] }
        values[i][j] = metric for axis1[i] × axis2[j]
    """
    cells: dict[tuple, list[float]] = defaultdict(list)
    for t in trades:
        a1 = t.get(axis1) or "Unknown"
        a2 = t.get(axis2) or "Unknown"
        cells[(a1, a2)].append(t.get("profit") or 0.0)

    labels_x = sorted({k[0] for k in cells})
    labels_y = sorted({k[1] for k in cells})

    def _cell_value(profits: list[float]) -> float:
        if not profits:
            return 0.0
        if metric == "win_rate":
            return round(len([p for p in profits if p > 0]) / len(profits), 4)
        if metric == "total_pnl":
            return round(sum(profits), 2)
        if metric == "profit_factor":
            wins = sum(p for p in profits if p > 0)
            losses = abs(sum(p for p in profits if p <= 0))
            return round(wins / losses, 2) if losses > 0 else 999.0
        return 0.0

    values = [
        [_cell_value(cells.get((x, y), [])) for y in labels_y]
        for x in labels_x
    ]
    return {"labels_x": labels_x, "labels_y": labels_y, "values": values}


def get_top_combinations(trades: list[dict], limit: int = 10) -> dict:
    """Return top N and worst N symbol+group combinations by win_rate."""
    combos: dict[tuple, list[float]] = defaultdict(list)
    for t in trades:
        key = (t.get("symbol", "??"), t.get("pattern_name") or t.get("execution_mode", "??"))
        combos[key].append(t.get("profit") or 0.0)

    combo_stats = []
    for (symbol, pattern), profits in combos.items():
        if len(profits) < 2:   # skip single-trade combos
            continue
        wins = [p for p in profits if p > 0]
        win_rate = len(wins) / len(profits)
        total_win = sum(wins)
        total_loss = abs(sum(p for p in profits if p <= 0))
        pf = total_win / total_loss if total_loss > 0 else 999.0
        combo_stats.append({
            "symbol": symbol,
            "pattern": pattern,
            "trades": len(profits),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(sum(profits), 2),
            "profit_factor": round(pf, 2),
        })

    sorted_stats = sorted(combo_stats, key=lambda c: c["win_rate"], reverse=True)
    return {
        "top": sorted_stats[:limit],
        "worst": sorted_stats[-limit:][::-1],
    }


def generate_recommendations(heatmap: dict, trades: list[dict]) -> list[str]:
    """Auto-generate recommendation strings from heatmap + combo data."""
    combos = get_top_combinations(trades, limit=3)
    recs = []

    if combos["top"]:
        best = combos["top"][0]
        recs.append(
            f"Best combination: {best['symbol']} + {best['pattern']} "
            f"({best['win_rate']*100:.0f}% WR, {best['profit_factor']:.1f}x PF, "
            f"{best['trades']} trades)"
        )

    if combos["worst"]:
        worst = combos["worst"][0]
        recs.append(
            f"Avoid: {worst['symbol']} + {worst['pattern']} "
            f"({worst['win_rate']*100:.0f}% WR over {worst['trades']} trades)"
        )

    # General guidance
    all_wins = [t.get("profit", 0) for t in trades if (t.get("profit") or 0) > 0]
    all_losses = [t.get("profit", 0) for t in trades if (t.get("profit") or 0) <= 0]
    if all_wins and all_losses:
        avg_win = sum(all_wins) / len(all_wins)
        avg_loss = abs(sum(all_losses) / len(all_losses))
        if avg_win / avg_loss < 1.0:
            recs.append("Risk/reward is unfavorable — consider widening take profit targets.")

    return recs
