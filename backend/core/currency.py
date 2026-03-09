import logging
import asyncio
import httpx
from datetime import datetime, timedelta, UTC

logger = logging.getLogger(__name__)

# In-memory cache
_rate_cache = {
    "usd_thb": 36.0,
    "last_updated": datetime.min.replace(tzinfo=UTC)
}

CACHE_TTL = timedelta(hours=6)
API_URL = "https://open.er-api.com/v6/latest/USD"

async def get_usd_thb_rate() -> float:
    """
    Fetch the latest USD to THB exchange rate from a public API.
    Uses an in-memory cache for 6 hours.
    """
    now = datetime.now(UTC)
    
    # Return cached rate if still valid
    if now - _rate_cache["last_updated"] < CACHE_TTL:
        return _rate_cache["usd_thb"]
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(API_URL)
            response.raise_for_status()
            data = response.json()
            
            if data.get("result") == "success":
                rate = data.get("rates", {}).get("THB")
                if rate:
                    _rate_cache["usd_thb"] = float(rate)
                    _rate_cache["last_updated"] = now
                    logger.info(f"Updated USD/THB exchange rate: {rate}")
                    return float(rate)
            
            logger.warning("Currency API response did not contain THB rate. Using fallback.")
    except Exception as e:
        logger.error(f"Failed to fetch exchange rate: {e}. Using fallback.")
    
    # Update last_updated even on failure to avoid spamming the API on every call
    # when it's down, but keep the old rate.
    _rate_cache["last_updated"] = now - CACHE_TTL + timedelta(minutes=5)
    return _rate_cache["usd_thb"]
