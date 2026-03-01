"""Tests for BacktestDataService — CSV parsing and MT5 error handling."""
import io
import pytest


@pytest.mark.asyncio
async def test_load_from_csv_basic():
    """CSV with correct headers parses to candle dicts."""
    from services.backtest_data import BacktestDataService

    csv_content = (
        "time,open,high,low,close,tick_volume\n"
        "2020-01-02 00:00:00,1.12345,1.12400,1.12300,1.12380,100\n"
        "2020-01-02 00:15:00,1.12380,1.12450,1.12350,1.12420,120\n"
    )
    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(csv_content))
    assert len(candles) == 2
    assert candles[0]["open"] == pytest.approx(1.12345)
    assert candles[1]["close"] == pytest.approx(1.12420)


@pytest.mark.asyncio
async def test_load_from_csv_missing_column_raises():
    """CSV missing required columns raises BacktestDataError."""
    from services.backtest_data import BacktestDataService, BacktestDataError

    csv_content = "time,open,high,low\n2020-01-02,1.1,1.2,1.0\n"
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="Missing columns"):
        await svc.load_from_csv(io.StringIO(csv_content))


@pytest.mark.asyncio
async def test_load_from_csv_case_insensitive_headers():
    """CSV headers are normalised to lowercase."""
    from services.backtest_data import BacktestDataService

    csv_content = (
        "Time,Open,High,Low,Close,Tick_Volume\n"
        "2020-01-02 00:00:00,1.1,1.2,1.0,1.15,50\n"
    )
    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(csv_content))
    assert len(candles) == 1


@pytest.mark.asyncio
async def test_load_from_csv_sorted_by_time():
    """Candles are returned sorted by time regardless of CSV row order."""
    from services.backtest_data import BacktestDataService

    csv_content = (
        "time,open,high,low,close,tick_volume\n"
        "2020-01-02 00:15:00,1.2,1.3,1.1,1.25,80\n"
        "2020-01-02 00:00:00,1.1,1.2,1.0,1.15,60\n"
    )
    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(csv_content))
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
