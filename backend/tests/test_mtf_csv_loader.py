import io
import pytest
from services.mtf_csv_loader import load_mt5_csv, MTFCSVError

# Exact MT5 export format (tab-separated, angle-bracket column names)
SAMPLE_MT5_CSV = """\
<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>
2017.01.02\t00:00:00\t143.878\t143.943\t143.851\t143.878\t61\t77850000\t200
2017.01.02\t00:15:00\t143.943\t143.943\t143.861\t143.862\t65\t80901000\t588
2017.01.02\t00:30:00\t143.862\t143.912\t143.842\t143.903\t48\t59850000\t400
"""


def test_load_mt5_csv_returns_ohlcv_list():
    from services.mtf_data import OHLCV
    candles = load_mt5_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert len(candles) == 3
    assert isinstance(candles[0], OHLCV)


def test_load_mt5_csv_parses_price_correctly():
    candles = load_mt5_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert candles[0].open == 143.878
    assert candles[0].high == 143.943
    assert candles[0].low == 143.851
    assert candles[0].close == 143.878
    assert candles[0].tick_volume == 61


def test_load_mt5_csv_datetime_is_utc():
    from datetime import timezone
    candles = load_mt5_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert candles[0].time.tzinfo == timezone.utc
    assert candles[0].time.year == 2017
    assert candles[0].time.month == 1
    assert candles[0].time.day == 2


def test_load_mt5_csv_sorted_oldest_first():
    candles = load_mt5_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert candles[0].time < candles[1].time < candles[2].time


def test_load_mt5_csv_raises_on_missing_columns():
    bad_csv = "col1\tcol2\n1\t2\n"
    with pytest.raises(MTFCSVError, match="Missing columns"):
        load_mt5_csv(io.StringIO(bad_csv))
