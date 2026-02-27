"""External alerting — Telegram notifications for critical trading events.

Silently skips if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not configured.
Never raises — alerting must not interrupt the trading pipeline.

Usage:
    await send_alert("*Kill switch ACTIVATED*\nReason: Max drawdown exceeded")
"""
import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_alert(message: str) -> None:
    """Send a Telegram message. No-op if Telegram is not configured."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    url = _TELEGRAM_URL.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.debug("Telegram alert sent | preview=%s", message[:60])
    except Exception as exc:
        logger.warning("Telegram alert failed (non-critical): %s", exc)
