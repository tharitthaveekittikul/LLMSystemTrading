from datetime import datetime
import zoneinfo
import pytest

from services.mtf_data import MTFMarketData, TimeframeData, OHLCV
from strategies.orb_strategy import ORBStrategy

NY_TZ = zoneinfo.ZoneInfo("America/New_York")

def _make_utc_dt(year, month, day, hour, minute):
    # Create NY time and convert to UTC to simulate live data
    ny_dt = datetime(year, month, day, hour, minute, tzinfo=NY_TZ)
    return ny_dt.astimezone(zoneinfo.ZoneInfo("UTC"))

def make_candle(dt_ny, open_p, high_p, low_p, close_p):
    return OHLCV(
        time=dt_ny,
        open=open_p, high=high_p, low=low_p, close=close_p,
        tick_volume=100
    )

def test_orb_strategy_bullish_fvg():
    strategy = ORBStrategy()
    
    # 9:30 AM NY time M5 candle
    m5_candles = [
        make_candle(_make_utc_dt(2023, 10, 10, 9, 25), 1.0, 1.1, 0.9, 1.05),
        make_candle(_make_utc_dt(2023, 10, 10, 9, 30), 1.05, 1.5, 1.0, 1.4), # High = 1.5, Low = 1.0
    ]
    
    # M1 candles around 9:36 AM closing above 1.5 with a bullish FVG
    m1_candles = [
        # FVG 3 candles ending at 9:38
        make_candle(_make_utc_dt(2023, 10, 10, 9, 36), 1.4, 1.45, 1.35, 1.38), # c1
        make_candle(_make_utc_dt(2023, 10, 10, 9, 37), 1.38, 1.55, 1.37, 1.55), # c2
        make_candle(_make_utc_dt(2023, 10, 10, 9, 38), 1.55, 1.6, 1.46, 1.52), # c3
    ]
    # Here, c1.high is 1.45, c3.low is 1.46. FVG exists (1.45 < 1.46).
    # Breakout exists: c3.close (1.52) > orb_high (1.5).
    
    market_data = MTFMarketData(
        symbol="EURUSD",
        primary_tf="M1",
        current_price=1.52,
        timeframes={
            "M5": TimeframeData(tf="M5", candles=m5_candles),
            "M1": TimeframeData(tf="M1", candles=m1_candles)
        },
        indicators={},
        trigger_time=_make_utc_dt(2023, 10, 10, 9, 38)
    )
    
    result = strategy.check_rule(market_data)
    assert result is not None
    assert result.action == "BUY"
    assert result.entry == 1.52
    assert result.stop_loss == 1.35 # c1.low
    assert result.take_profit == 1.52 + ((1.52 - 1.35) * 3)
    assert result.confidence == 0.9
    assert result.pattern_name == "ORB_Bullish_FVG"

def test_orb_strategy_bearish_fvg():
    strategy = ORBStrategy()
    
    # 9:30 AM NY time M5 candle
    m5_candles = [
        make_candle(_make_utc_dt(2023, 10, 10, 9, 30), 1.05, 1.5, 1.0, 1.4), # High = 1.5, Low = 1.0
    ]
    
    # M1 candles breaking below 1.0 with a bearish FVG
    m1_candles = [
        make_candle(_make_utc_dt(2023, 10, 10, 9, 36), 1.1, 1.15, 1.05, 1.05), # c1
        make_candle(_make_utc_dt(2023, 10, 10, 9, 37), 1.05, 1.08, 0.9, 0.95), # c2
        make_candle(_make_utc_dt(2023, 10, 10, 9, 38), 0.95, 1.04, 0.85, 0.9), # c3
    ]
    # c1.low = 1.05, c3.high = 1.04. Bearish FVG exists (1.05 > 1.04)
    # Breakout exists: c3.close (0.9) < orb_low (1.0)
    
    market_data = MTFMarketData(
        symbol="EURUSD",
        primary_tf="M1",
        current_price=0.9,
        timeframes={
            "M5": TimeframeData(tf="M5", candles=m5_candles),
            "M1": TimeframeData(tf="M1", candles=m1_candles)
        },
        indicators={},
        trigger_time=_make_utc_dt(2023, 10, 10, 9, 38)
    )
    
    result = strategy.check_rule(market_data)
    assert result is not None
    assert result.action == "SELL"
    assert result.entry == 0.9
    assert result.stop_loss == 1.15 # c1.high
    assert result.take_profit == 0.9 - ((1.15 - 0.9) * 3)
    
def test_orb_strategy_one_trade_per_day():
    strategy = ORBStrategy()
    strategy.last_traded_date = "2023-10-10"
    
    # 9:30 AM NY time M5 candle
    m5_candles = [
        make_candle(_make_utc_dt(2023, 10, 10, 9, 30), 1.05, 1.5, 1.0, 1.4),
    ]
    m1_candles = [
        make_candle(_make_utc_dt(2023, 10, 10, 9, 36), 1.4, 1.45, 1.35, 1.38),
        make_candle(_make_utc_dt(2023, 10, 10, 9, 37), 1.38, 1.55, 1.37, 1.55),
        make_candle(_make_utc_dt(2023, 10, 10, 9, 38), 1.55, 1.6, 1.46, 1.52),
    ]
    
    market_data = MTFMarketData(
        symbol="EURUSD",
        primary_tf="M1",
        current_price=1.52,
        timeframes={
            "M5": TimeframeData(tf="M5", candles=m5_candles),
            "M1": TimeframeData(tf="M1", candles=m1_candles)
        },
        indicators={},
        trigger_time=_make_utc_dt(2023, 10, 10, 9, 38)
    )
    
    result = strategy.check_rule(market_data)
    # Should not trade because already traded on 2023-10-10
    assert result is None

