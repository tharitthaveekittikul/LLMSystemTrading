import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account
from db.postgres import get_db
from mt5.bridge import AccountCredentials, MT5Bridge

logger = logging.getLogger(__name__)

router = APIRouter()

TIMEFRAME_MAP: dict[str, int] = {
    "M1":  1,
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  16385,
    "H4":  16388,
    "D1":  16408,
    "W1":  32769,
}


@router.get("/{symbol}/{timeframe}")
async def get_ohlcv(
    symbol: str = Path(..., description="e.g. XAUUSD"),
    timeframe: str = Path(..., description="M1 M5 M15 M30 H1 H4 D1 W1"),
    account_id: int = Query(..., description="Account to fetch data from"),
    count: int = Query(300, ge=50, le=1000),
    db: AsyncSession = Depends(get_db),
):
    tf_int = TIMEFRAME_MAP.get(timeframe.upper())
    if tf_int is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown timeframe '{timeframe}'. Valid: {list(TIMEFRAME_MAP)}",
        )

    row = (
        await db.execute(select(Account).where(Account.id == account_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")

    creds = AccountCredentials(
        login=row.login,
        password=decrypt(row.password_encrypted),
        server=row.server,
        path=row.mt5_path or settings.mt5_path,
    )

    try:
        async with MT5Bridge(creds) as bridge:
            # Resolve broker-specific symbol name (e.g. XAUUSD -> XAUUSD.s) — same
            # resolution the strategy pipeline uses, so the chart stays broker-agnostic.
            mt5_symbol = await bridge.get_broker_symbol(symbol)
            candles = await bridge.get_rates(mt5_symbol, tf_int, count, require_connected=False)
            tick = await bridge.get_tick(mt5_symbol)
    except Exception as exc:
        logger.error("get_rates(%s, %s) failed: %s", symbol, timeframe, exc)
        raise HTTPException(status_code=503, detail=str(exc))

    # MT5 bar times are in broker server timezone, not UTC.
    # Detect the offset by comparing the latest tick time to real UTC,
    # then subtract it so the frontend receives true UTC timestamps.
    broker_offset_s = 0
    if tick and "time" in tick:
        utc_now = int(datetime.now(UTC).timestamp())
        raw_offset = int(tick["time"]) - utc_now
        # Round to nearest hour (ignore sub-minute drift)
        broker_offset_s = round(raw_offset / 3600) * 3600
        if broker_offset_s:
            logger.debug("Broker UTC offset detected: %+dh", broker_offset_s // 3600)

    result = []
    for c in candles:
        t = c["time"]
        ts = int(t.timestamp()) if hasattr(t, "timestamp") else int(t)
        result.append({
            "time": ts - broker_offset_s,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low":  float(c["low"]),
            "close": float(c["close"]),
            "volume": int(c.get("tick_volume", 0)),
        })

    logger.debug(
        "get_ohlcv(%s -> %s, %s, account=%d) -> %d candles",
        symbol, mt5_symbol, timeframe.upper(), account_id, len(result),
    )
    return {"symbol": mt5_symbol, "candles": result}
