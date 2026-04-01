"""Chart Vision Analysis — captures MT5 chart screenshots and sends to LLM Vision.

Optional enhancement to the signal pipeline. The main pipeline must work
without this module (vision is a supplementary context signal only).
"""
import base64
import io
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage

from ai.orchestrator import _build_llm

logger = logging.getLogger(__name__)


def generate_ohlcv_chart(ohlcv: list[dict], symbol: str = "", timeframe: str = "") -> str | None:
    """Render a candlestick chart from OHLCV data. Returns base64 PNG string or None on error.

    Uses the last 50 candles. Requires mplfinance to be installed.
    OHLCV dicts must have keys: time, open, high, low, close, volume.
    """
    try:
        import mplfinance as mpf
        import pandas as pd

        df = pd.DataFrame(ohlcv)
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
        # MT5 uses tick_volume; accept either key
        if "volume" not in df.columns and "tick_volume" in df.columns:
            df = df.rename(columns={"tick_volume": "volume"})
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[cols].tail(50)

        buf = io.BytesIO()
        title = f"{symbol} {timeframe}".strip()
        mpf.plot(df, type="candle", style="charles", title=title,
                 savefig=dict(fname=buf, dpi=100))
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as exc:
        logger.warning("Chart generation failed: %s", exc)
        return None


async def analyze_chart_screenshot(image_path: str | Path) -> str:
    """Send a chart screenshot to the LLM and return a text pattern analysis."""
    path = Path(image_path)
    if not path.exists():
        return ""

    with open(path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    ext = path.suffix.lower().lstrip(".")
    media_type = f"image/{ext if ext in ('png', 'jpeg', 'jpg', 'gif', 'webp') else 'png'}"

    llm = _build_llm()

    message = HumanMessage(
        content=[
            {
                "type": "text",
                "text": (
                    "Analyze this trading chart. Identify: trend direction, "
                    "key support/resistance levels, candlestick patterns, and "
                    "any chart patterns (head & shoulders, double top/bottom, "
                    "flags, wedges). Be concise and technical."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{image_data}"},
            },
        ]
    )

    response = await llm.ainvoke([message])
    from ai.orchestrator import log_llm_usage
    log_llm_usage(response, llm, "chart_vision")
    return response.content
