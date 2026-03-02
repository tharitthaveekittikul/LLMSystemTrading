# backend/tests/test_hmm_service.py
import numpy as np
import pytest

from services.hmm_service import HMMService

_VALID_REGIMES = {"trending_bullish", "trending_bearish", "ranging", "high_volatility"}


@pytest.fixture
def sample_candles_200():
    rng = np.random.default_rng(42)
    closes = 1.0850 + np.cumsum(rng.normal(0, 0.0005, 200))
    result = []
    for i, c in enumerate(closes):
        h  = c + abs(rng.normal(0, 0.0002))
        lo = c - abs(rng.normal(0, 0.0002))
        result.append({
            "open":        float(closes[i - 1] if i > 0 else c),
            "high":        float(h),
            "low":         float(lo),
            "close":       float(c),
            "tick_volume": float(rng.integers(500, 5000)),
        })
    return result


def test_train_predict_returns_valid_regime(tmp_path, sample_candles_200):
    svc = HMMService("EURUSD", "D1")
    svc._model_path = str(tmp_path / "model.pkl")
    svc.train(sample_candles_200)
    result = svc.predict(sample_candles_200[-50:])
    assert result["regime"] in _VALID_REGIMES
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["state"] in {0, 1, 2, 3}


def test_predict_without_model_returns_unknown():
    svc = HMMService("EURUSD_NOMODEL", "D1")
    svc._model_path = "/nonexistent/path.pkl"
    svc.model = None
    result = svc.predict([])
    assert result["regime"] == "unknown"
    assert result["confidence"] == 0.0


def test_persist_and_reload(tmp_path, sample_candles_200):
    path = str(tmp_path / "model.pkl")
    svc1 = HMMService("USDJPY", "D1")
    svc1._model_path = path
    svc1.train(sample_candles_200)

    svc2 = HMMService("USDJPY", "D1")
    svc2._model_path = path
    svc2._load_model()
    assert svc2.model is not None
    assert svc2._train_mean is not None
    assert svc2._train_std is not None


def test_multiple_symbols_have_independent_labels(tmp_path, sample_candles_200):
    """Bug fix #1: no module-level global — each instance has its own labels dict."""
    svc_eur = HMMService("EURUSD", "D1")
    svc_eur._model_path = str(tmp_path / "eur.pkl")
    svc_eur.train(sample_candles_200)

    svc_xau = HMMService("XAUUSD", "D1")
    svc_xau._model_path = str(tmp_path / "xau.pkl")
    svc_xau.train(sample_candles_200)

    assert svc_eur.regime_labels is not svc_xau.regime_labels


def test_predict_uses_training_stats_not_window_stats(tmp_path, sample_candles_200):
    """Bug fix #2: training mean/std must be stable across predict() calls."""
    svc = HMMService("EURUSD", "D1")
    svc._model_path = str(tmp_path / "model.pkl")
    svc.train(sample_candles_200)

    mean_before = svc._train_mean.copy()
    std_before  = svc._train_std.copy()
    svc.predict(sample_candles_200[-50:])
    np.testing.assert_array_equal(svc._train_mean, mean_before)
    np.testing.assert_array_equal(svc._train_std,  std_before)


def test_train_raises_on_too_few_candles(tmp_path):
    svc = HMMService("EURUSD", "D1")
    svc._model_path = str(tmp_path / "model.pkl")
    with pytest.raises(ValueError, match="at least 50"):
        svc.train([
            {"close": 1.0, "high": 1.01, "low": 0.99, "tick_volume": 1000}
        ] * 10)
