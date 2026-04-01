"""
Technical indicators and trendline utilities for the multi-agent trading pipeline.
"""

import base64
import io
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _ensure_pandas_ta() -> None:
    try:
        import pandas_ta  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "pandas-ta is required for compute_indicators(). "
            "Install with: uv add pandas-ta"
        ) from e


def _ensure_mplfinance() -> None:
    try:
        import mplfinance  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "mplfinance is required for render_trendline_chart(). "
            "Install with: uv add mplfinance"
        ) from e


def _ohlcv_to_dataframe(ohlcv: list[dict]) -> pd.DataFrame:
    """Convert list of OHLCV dicts to a DataFrame, tolerating tick_volume column."""
    df = pd.DataFrame(ohlcv)

    # Normalise volume column name
    if "volume" not in df.columns and "tick_volume" in df.columns:
        df = df.rename(columns={"tick_volume": "volume"})

    # Ensure datetime index for mplfinance compatibility
    if "time" in df.columns:
        if pd.api.types.is_numeric_dtype(df["time"]):
            # MT5 copy_rates_from_pos() returns Unix timestamps (seconds)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
        else:
            df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")

    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def compute_indicators(ohlcv: list[dict]) -> dict:
    """
    Compute momentum/oscillator indicators from OHLCV data using pandas-ta.

    Parameters
    ----------
    ohlcv:
        List of dicts with keys: time, open, high, low, close, volume
        (tick_volume is also accepted in place of volume).

    Returns
    -------
    dict with keys: rsi, macd_line, macd_signal, macd_histogram,
                    stoch_k, stoch_d, roc, willr

    Raises
    ------
    ValueError
        If fewer than 50 candles are provided.
    ImportError
        If pandas-ta is not installed.
    """
    _ensure_pandas_ta()
    import pandas_ta as ta

    if len(ohlcv) < 50:
        raise ValueError(
            f"compute_indicators requires at least 50 candles, got {len(ohlcv)}."
        )

    df = _ohlcv_to_dataframe(ohlcv)

    # RSI(14)
    df.ta.rsi(length=14, append=True)

    # MACD(12, 26, 9)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)

    # Stochastic(14, 3, 3)
    df.ta.stoch(k=14, d=3, smooth_k=3, append=True)

    # Rate of Change(10)
    df.ta.roc(length=10, append=True)

    # Williams %R(14)
    df.ta.willr(length=14, append=True)

    last = df.iloc[-1]

    def _get(col_prefix: str) -> Optional[float]:
        """Return the first column matching the prefix (case-insensitive)."""
        matches = [c for c in df.columns if c.upper().startswith(col_prefix.upper())]
        if not matches:
            return float("nan")
        val = last[matches[0]]
        return float(val) if pd.notna(val) else float("nan")

    result = {
        "rsi": _get("RSI_14"),
        "macd_line": _get("MACD_12_26_9"),
        "macd_signal": _get("MACDs_12_26_9"),
        "macd_histogram": _get("MACDh_12_26_9"),
        "stoch_k": _get("STOCHk_14_3_3"),
        "stoch_d": _get("STOCHd_14_3_3"),
        "roc": _get("ROC_10"),
        "willr": _get("WILLR_14"),
    }

    logger.debug("compute_indicators: last-row values %s", result)
    return result


def fit_trendlines(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    lookback: int = 50,
) -> tuple[float, float, float, float]:
    """
    Fit support and resistance trendlines using linear regression.

    Uses numpy polyfit (degree=1) on the lows (support) and highs (resistance)
    of the last `lookback` bars.

    Parameters
    ----------
    high, low, close:
        1-D numpy arrays of OHLCV bar data (same length).
    lookback:
        Number of bars from the end to use.

    Returns
    -------
    (support_slope, support_intercept, resist_slope, resist_intercept)
        Line equation: price = slope * x + intercept  (x = bar index 0..lookback-1)
    """
    n = min(lookback, len(low))
    lows = low[-n:]
    highs = high[-n:]

    x = np.arange(n, dtype=float)

    # Support: linear regression on lows
    support_coeffs = np.polyfit(x, lows, 1)
    support_slope = float(support_coeffs[0])
    support_intercept = float(support_coeffs[1])

    # Resistance: linear regression on highs
    resist_coeffs = np.polyfit(x, highs, 1)
    resist_slope = float(resist_coeffs[0])
    resist_intercept = float(resist_coeffs[1])

    logger.debug(
        "fit_trendlines: support (%.6f, %.6f)  resist (%.6f, %.6f)",
        support_slope,
        support_intercept,
        resist_slope,
        resist_intercept,
    )
    return support_slope, support_intercept, resist_slope, resist_intercept


def render_trendline_chart(
    ohlcv: list[dict],
    support_slope: float,
    support_intercept: float,
    resist_slope: float,
    resist_intercept: float,
    lookback: int = 50,
) -> str:
    """
    Render a candlestick chart with support (blue) and resistance (red) trendlines.

    Parameters
    ----------
    ohlcv:
        List of OHLCV dicts (time, open, high, low, close, volume / tick_volume).
    support_slope, support_intercept:
        Coefficients for the support line.
    resist_slope, resist_intercept:
        Coefficients for the resistance line.
    lookback:
        Number of trailing candles to display.

    Returns
    -------
    Base64-encoded PNG string, or empty string on failure.
    """
    try:
        _ensure_mplfinance()
    except ImportError as exc:
        logger.warning("render_trendline_chart: %s", exc)
        return ""

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import mplfinance as mpf

        df = _ohlcv_to_dataframe(ohlcv)
        df = df.iloc[-lookback:]

        n = len(df)
        x = np.arange(n, dtype=float)

        support_vals = support_slope * x + support_intercept
        resist_vals = resist_slope * x + resist_intercept

        # Build additional lines as mplfinance addplot
        ap_support = mpf.make_addplot(
            pd.Series(support_vals, index=df.index),
            color="blue",
            width=1.5,
            linestyle="--",
        )
        ap_resist = mpf.make_addplot(
            pd.Series(resist_vals, index=df.index),
            color="red",
            width=1.5,
            linestyle="--",
        )

        buf = io.BytesIO()
        mpf.plot(
            df,
            type="candle",
            style="charles",
            addplot=[ap_support, ap_resist],
            savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
            show_nontrading=False,
        )
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode("utf-8")
        plt.close("all")

        logger.debug("render_trendline_chart: chart encoded (%d bytes)", len(encoded))
        return encoded

    except Exception as exc:  # noqa: BLE001
        logger.warning("render_trendline_chart failed: %s", exc)
        return ""
