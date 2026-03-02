# backend/tests/test_hmm_features.py
import numpy as np
import pytest

from services.hmm_features import extract_features


@pytest.fixture
def sample_candles_200():
    """200 synthetic OHLCV candles with realistic FX values."""
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


def test_extract_features_shape(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert X.shape == (200, 4)


def test_extract_features_no_nan_or_inf(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert not np.any(np.isnan(X))
    assert not np.any(np.isinf(X))


def test_extract_features_column_ranges(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert abs(X[:, 0]).max() < 0.1      # log_return — small for FX
    assert (X[:, 1] >= 0).all()           # realized_vol — non-negative
    assert (X[:, 2] > 0).all()            # atr_norm — small positive ratio
    assert X[:, 2].max() < 0.1
    assert (X[:, 3] > 0).all()            # volume_ratio — positive
