"""Tests for MTFBacktestLoader — multi-TF candle alignment with no data leak."""
import io
from datetime import datetime, timezone, timedelta

import pytest
from services.mtf_data import OHLCV, MTFMarketData
from services.mtf_backtest_loader import MTFBacktestLoader


def _make_csv_content(n: int, start: datetime, tf_minutes: int,
                       base: float = 1.1) -> str:
    """Generate MT5-format CSV string with n candles."""
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    t = start
    price = base
    for _ in range(n):
        date_str = t.strftime("%Y.%m.%d")
        time_str = t.strftime("%H:%M:%S")
        lines.append(f"{date_str}\t{time_str}\t{price:.5f}\t{price+0.001:.5f}\t"
                     f"{price-0.001:.5f}\t{price:.5f}\t100\t1000000\t10")
        t += timedelta(minutes=tf_minutes)
        price += 0.00001
    return "\n".join(lines) + "\n"


def test_loader_yields_mtf_market_data():
    start = datetime(2020, 1, 2, tzinfo=timezone.utc)
    m15_csv = io.StringIO(_make_csv_content(100, start, 15))
    h1_csv = io.StringIO(_make_csv_content(30, start, 60))
    m1_csv = io.StringIO(_make_csv_content(300, start, 1))

    loader = MTFBacktestLoader({"M15": m15_csv, "H1": h1_csv, "M1": m1_csv})
    items = list(loader.iter_primary_closes(
        primary_tf="M15",
        context_tfs=["H1", "M1"],
        candle_counts={"H1": 5, "M15": 10, "M1": 5},
        start_date=start + timedelta(hours=3),
        end_date=start + timedelta(hours=6),
    ))
    assert len(items) > 0
    first = items[0]
    assert isinstance(first, MTFMarketData)
    assert first.primary_tf == "M15"
    assert "H1" in first.timeframes
    assert "M15" in first.timeframes
    assert "M1" in first.timeframes


def test_loader_no_future_data_leak():
    """H1 candles returned at a given M15 time must all close BEFORE that time."""
    start = datetime(2020, 1, 2, tzinfo=timezone.utc)
    m15_csv = io.StringIO(_make_csv_content(200, start, 15))
    h1_csv = io.StringIO(_make_csv_content(50, start, 60))
    m1_csv = io.StringIO(_make_csv_content(500, start, 1))

    loader = MTFBacktestLoader({"M15": m15_csv, "H1": h1_csv, "M1": m1_csv})
    for md in loader.iter_primary_closes(
        primary_tf="M15", context_tfs=["H1", "M1"],
        candle_counts={"H1": 20, "M15": 10, "M1": 5},
        start_date=start + timedelta(hours=2),
        end_date=start + timedelta(hours=5),
    ):
        trigger = md.trigger_time
        for tf_name, tf_data in md.timeframes.items():
            for candle in tf_data.candles:
                assert candle.time <= trigger, (
                    f"Future data leak: {tf_name} candle at {candle.time} > trigger {trigger}"
                )


def test_loader_respects_candle_counts():
    start = datetime(2020, 1, 2, tzinfo=timezone.utc)
    m15_csv = io.StringIO(_make_csv_content(200, start, 15))
    h1_csv = io.StringIO(_make_csv_content(50, start, 60))
    m1_csv = io.StringIO(_make_csv_content(500, start, 1))

    loader = MTFBacktestLoader({"M15": m15_csv, "H1": h1_csv, "M1": m1_csv})
    items = list(loader.iter_primary_closes(
        primary_tf="M15", context_tfs=["H1", "M1"],
        candle_counts={"H1": 5, "M15": 8, "M1": 3},
        start_date=start + timedelta(hours=5),
        end_date=start + timedelta(hours=8),
    ))
    for md in items:
        assert len(md.timeframes["H1"].candles) <= 5
        assert len(md.timeframes["M15"].candles) <= 8
        assert len(md.timeframes["M1"].candles) <= 3
