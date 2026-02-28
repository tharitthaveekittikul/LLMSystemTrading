from unittest.mock import MagicMock
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from services.scheduler import _make_trigger, _job_id, CANDLE_CRON

def _mock_strategy(trigger_type, timeframe="M15", interval_minutes=15):
    s = MagicMock()
    s.trigger_type = trigger_type
    s.timeframe = timeframe
    s.interval_minutes = interval_minutes
    return s

def test_make_trigger_interval():
    assert isinstance(_make_trigger(_mock_strategy("interval", interval_minutes=30)), IntervalTrigger)

def test_make_trigger_candle_close():
    assert isinstance(_make_trigger(_mock_strategy("candle_close")), CronTrigger)

def test_make_trigger_unknown_timeframe_defaults():
    assert isinstance(_make_trigger(_mock_strategy("candle_close", timeframe="UNKNOWN")), CronTrigger)

def test_job_id_format():
    assert _job_id(42, "EURUSD") == "strat_42_EURUSD"

def test_candle_cron_covers_all_timeframes():
    for tf in ("M15", "M30", "H1", "H4", "D1"):
        assert tf in CANDLE_CRON
