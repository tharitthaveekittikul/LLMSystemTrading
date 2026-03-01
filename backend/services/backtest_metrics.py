"""BacktestMetrics — compute performance statistics from a list of backtest trades.

All functions are pure Python with no I/O — easy to unit-test.
"""
from __future__ import annotations

import math
from collections import defaultdict


def compute_metrics(trades: list[dict], initial_balance: float) -> dict:
    """Compute all performance metrics from completed backtest trades.

    Args:
        trades: list of dicts with keys: profit (float), equity_after (float).
                Must be in chronological order.
        initial_balance: starting portfolio value.

    Returns:
        dict with keys: total_trades, win_rate, profit_factor, expectancy,
        max_drawdown_pct, recovery_factor, sharpe_ratio, sortino_ratio,
        total_return_pct, avg_win, avg_loss, max_consec_wins, max_consec_losses
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_drawdown_pct": 0.0,
            "recovery_factor": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "total_return_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_consec_wins": 0,
            "max_consec_losses": 0,
        }

    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total_trades = len(profits)
    win_rate = len(wins) / total_trades
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0  # negative value
    loss_rate = len(losses) / total_trades
    expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)  # avg_loss is negative

    # Max drawdown %
    peak = initial_balance
    max_dd_abs = 0.0
    running = initial_balance
    for p in profits:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd_abs:
            max_dd_abs = dd
    max_drawdown_pct = (max_dd_abs / initial_balance) * 100 if initial_balance > 0 else 0.0

    # Total return %
    total_return = sum(profits)
    total_return_pct = (total_return / initial_balance) * 100 if initial_balance > 0 else 0.0

    # Recovery factor
    recovery_factor = total_return / max_dd_abs if max_dd_abs > 0 else float("inf")

    # Sharpe / Sortino (annualised, assuming ~252 trading days)
    sharpe_ratio = _sharpe(profits)
    sortino_ratio = _sortino(profits)

    # Consecutive wins/losses
    max_consec_wins, max_consec_losses = _consecutive(profits)

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 9999.0,
        "expectancy": round(expectancy, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "recovery_factor": round(recovery_factor, 4) if recovery_factor != float("inf") else 9999.0,
        "sharpe_ratio": round(sharpe_ratio, 4),
        "sortino_ratio": round(sortino_ratio, 4),
        "total_return_pct": round(total_return_pct, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
    }


def compute_monthly_pnl(trades: list[dict]) -> list[dict]:
    """Return [{year, month, pnl, trade_count}] sorted chronologically.

    trades dicts must have: profit (float), exit_time (datetime).
    """
    monthly: dict[tuple[int, int], list[float]] = defaultdict(list)
    for t in trades:
        if t.get("exit_time") and t.get("profit") is not None:
            key = (t["exit_time"].year, t["exit_time"].month)
            monthly[key].append(t["profit"])
    return [
        {
            "year": y,
            "month": m,
            "pnl": round(sum(ps), 4),
            "trade_count": len(ps),
        }
        for (y, m), ps in sorted(monthly.items())
    ]


# ── Private helpers ────────────────────────────────────────────────────────────

def _sharpe(profits: list[float]) -> float:
    n = len(profits)
    if n < 2:
        return 0.0
    mean = sum(profits) / n
    variance = sum((p - mean) ** 2 for p in profits) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def _sortino(profits: list[float]) -> float:
    n = len(profits)
    if n < 2:
        return 0.0
    mean = sum(profits) / n
    downside = [p for p in profits if p < 0]
    if not downside:
        return float("inf")
    downside_var = sum(p ** 2 for p in downside) / n
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(252)


def _consecutive(profits: list[float]) -> tuple[int, int]:
    max_wins = max_losses = cur_wins = cur_losses = 0
    for p in profits:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
        elif p < 0:
            cur_losses += 1
            cur_wins = 0
        else:
            cur_wins = cur_losses = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return max_wins, max_losses
