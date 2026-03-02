# backend/services/hmm_features.py
"""Feature extraction for HMM training and inference."""
import numpy as np


def extract_features(candles: list[dict]) -> np.ndarray:
    """
    Returns shape (n_samples, 4) array:
      col 0: log_return
      col 1: realized_vol  (14-bar rolling std of log_return)
      col 2: atr_norm      (ATR14 / close)
      col 3: volume_ratio  (volume / rolling_mean_vol_20)
    """
    closes  = np.array([c["close"]       for c in candles], dtype=float)
    highs   = np.array([c["high"]        for c in candles], dtype=float)
    lows    = np.array([c["low"]         for c in candles], dtype=float)
    volumes = np.array([c["tick_volume"] for c in candles], dtype=float)

    log_ret = np.diff(np.log(closes), prepend=np.log(closes[0]))

    # Realized vol: rolling 14-bar std
    rvol = np.array([
        log_ret[max(0, i - 13):i + 1].std() if i >= 13 else log_ret[:i + 1].std()
        for i in range(len(log_ret))
    ])

    # True range using explicit shifted close (avoids np.roll index-0 edge case)
    prev_closes = np.empty_like(closes)
    prev_closes[0] = closes[0]
    prev_closes[1:] = closes[:-1]
    tr = np.maximum(
        highs - lows,
        np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)),
    )
    atr      = np.array([tr[max(0, i - 13):i + 1].mean() for i in range(len(tr))])
    atr_norm = atr / closes

    # Volume ratio
    vol_mean  = np.array([volumes[max(0, i - 19):i + 1].mean() for i in range(len(volumes))])
    vol_ratio = volumes / np.where(vol_mean > 0, vol_mean, 1.0)

    return np.column_stack([log_ret, rvol, atr_norm, vol_ratio])
