"""Chart Vision Analysis — captures MT5 chart screenshots and sends to LLM Vision.

Optional enhancement to the signal pipeline. The main pipeline must work
without this module (vision is a supplementary context signal only).
"""
import base64
from pathlib import Path

from langchain_core.messages import HumanMessage

from ai.orchestrator import _build_llm


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
    return response.content
