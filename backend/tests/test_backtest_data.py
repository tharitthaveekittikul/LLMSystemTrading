"""Tests for BacktestDataService — CSV parsing and MT5 error handling."""
import io
import pytest

# MT5 export format (tab-separated, angle-bracket headers)
SAMPLE_MT5_CSV = (
    "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
    "2020.01.02\t00:00:00\t1.12345\t1.12400\t1.12300\t1.12380\t100\t0\t15\n"
    "2020.01.02\t00:15:00\t1.12380\t1.12450\t1.12350\t1.12420\t120\t0\t18\n"
)


@pytest.mark.asyncio
async def test_load_from_csv_accepts_mt5_format():
    """MT5 tab-delimited CSV with angle-bracket headers parses correctly."""
    from services.backtest_data import BacktestDataService

    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert len(candles) == 2
    assert candles[0]["open"] == pytest.approx(1.12345)
    assert candles[1]["close"] == pytest.approx(1.12420)


@pytest.mark.asyncio
async def test_load_from_csv_includes_spread():
    """Result candle dicts include 'spread' key from <SPREAD> column."""
    from services.backtest_data import BacktestDataService

    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert candles[0]["spread"] == 15
    assert candles[1]["spread"] == 18


@pytest.mark.asyncio
async def test_load_from_csv_missing_required_column_raises():
    """CSV missing required columns raises BacktestDataError."""
    from services.backtest_data import BacktestDataService, BacktestDataError

    bad_csv = "col1\tcol2\n1\t2\n"
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="Missing columns"):
        await svc.load_from_csv(io.StringIO(bad_csv))


@pytest.mark.asyncio
async def test_load_from_csv_sorted_by_time():
    """Candles are returned sorted oldest-first regardless of CSV order."""
    from services.backtest_data import BacktestDataService

    # Rows in reverse order
    csv = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2020.01.02\t00:15:00\t1.20000\t1.30000\t1.10000\t1.25000\t80\t0\t10\n"
        "2020.01.02\t00:00:00\t1.10000\t1.20000\t1.00000\t1.15000\t60\t0\t10\n"
    )
    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(csv))
    assert candles[0]["open"] == pytest.approx(1.1)
    assert candles[1]["open"] == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_load_from_mt5_empty_raises():
    """When MT5Bridge returns empty list, BacktestDataError is raised."""
    from unittest.mock import AsyncMock
    from services.backtest_data import BacktestDataService, BacktestDataError

    bridge = AsyncMock()
    bridge.get_rates_range = AsyncMock(return_value=[])
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="No data returned"):
        await svc.load_from_mt5(bridge, "EURUSD", 16408, None, None)


@pytest.mark.asyncio
async def test_load_from_mt5_propagates_error():
    """When MT5Bridge raises, BacktestDataError wraps it."""
    from unittest.mock import AsyncMock
    from services.backtest_data import BacktestDataService, BacktestDataError

    bridge = AsyncMock()
    bridge.get_rates_range = AsyncMock(side_effect=RuntimeError("MT5 not connected"))
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="MT5 fetch failed"):
        await svc.load_from_mt5(bridge, "EURUSD", 16408, None, None)
