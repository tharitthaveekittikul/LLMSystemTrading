from datetime import datetime, timezone, timedelta
from services.mtf_data import OHLCV, TimeframeData, MTFMarketData


def _make_ohlcv(n: int, base: float = 1.1, tf_minutes: int = 15) -> list[OHLCV]:
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    result = []
    for i in range(n):
        result.append(OHLCV(
            time=t, open=base, high=base + 0.001, low=base - 0.001, close=base, tick_volume=100
        ))
        t += timedelta(minutes=tf_minutes)
    return result


def test_ohlcv_is_dataclass():
    c = OHLCV(time=datetime(2020, 1, 2, tzinfo=timezone.utc),
               open=1.1, high=1.101, low=1.099, close=1.1, tick_volume=50)
    assert c.close == 1.1
    assert c.tick_volume == 50


def test_timeframe_data_holds_candles():
    candles = _make_ohlcv(10)
    tf = TimeframeData(tf="M15", candles=candles)
    assert tf.tf == "M15"
    assert len(tf.candles) == 10


def test_mtf_market_data_structure():
    h1 = TimeframeData(tf="H1", candles=_make_ohlcv(20, tf_minutes=60))
    m15 = TimeframeData(tf="M15", candles=_make_ohlcv(10, tf_minutes=15))
    m1 = TimeframeData(tf="M1", candles=_make_ohlcv(5, tf_minutes=1))
    md = MTFMarketData(
        symbol="XAUUSD",
        primary_tf="M15",
        current_price=1.1,
        timeframes={"H1": h1, "M15": m15, "M1": m1},
        indicators={"sma_20": 1.09},
        trigger_time=datetime(2020, 1, 2, 1, 0, tzinfo=timezone.utc),
    )
    assert md.symbol == "XAUUSD"
    assert "H1" in md.timeframes
    assert md.timeframes["M15"].tf == "M15"
