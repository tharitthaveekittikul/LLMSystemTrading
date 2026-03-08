"""Integration test: run HarmonicStrategy through MTFBacktestLoader with synthetic candles."""
import asyncio
import io
import math
from datetime import datetime, timezone, timedelta

import pytest


def _make_csv(n: int, start: datetime, tf_minutes: int, base: float = 1.1) -> io.StringIO:
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    t = start
    price = base
    for i in range(n):
        # Sine wave to create natural swing highs/lows for pivot detection
        offset = 0.005 * math.sin(i * 0.3)
        high = price + abs(offset) + 0.002
        low = price - abs(offset) - 0.001
        close = price + offset
        lines.append(
            f"{t.strftime('%Y.%m.%d')}\t{t.strftime('%H:%M:%S')}\t"
            f"{price:.5f}\t{high:.5f}\t{low:.5f}\t{close:.5f}\t100\t1000000\t10"
        )
        t += timedelta(minutes=tf_minutes)
        price = close
    return io.StringIO("\n".join(lines) + "\n")


async def test_harmonic_strategy_backtest_runs_without_error():
    from services.mtf_backtest_loader import MTFBacktestLoader
    from strategies.harmonic.harmonic_strategy import HarmonicStrategy

    start = datetime(2020, 1, 2, tzinfo=timezone.utc)
    m15_csv = _make_csv(300, start, 15, base=1.10)
    h1_csv  = _make_csv(80, start, 60, base=1.10)
    m1_csv  = _make_csv(1200, start, 1, base=1.10)

    loader = MTFBacktestLoader({"M15": m15_csv, "H1": h1_csv, "M1": m1_csv})
    strategy = HarmonicStrategy()

    # Collect MTFMarketData items
    items = list(loader.iter_primary_closes(
        primary_tf="M15", context_tfs=["H1", "M1"],
        candle_counts={"H1": 20, "M15": 50, "M1": 5},
        start_date=start + timedelta(hours=2),
        end_date=start + timedelta(hours=48),
    ))
    assert len(items) > 0

    # Run strategy on each item
    results = []
    for md in items[:50]:   # test first 50 triggers
        md.symbol = "EURUSD"
        result = await strategy.run(md)
        results.append(result)

    actions = [r.action for r in results]
    assert "HOLD" in actions   # most will be HOLD (no pattern)
    # May or may not have BUY_LIMIT/SELL_LIMIT depending on synthetic data — just check no exception
    print(f"Actions: {set(actions)}")
