"""Live MT5 account info and tradable symbol listing."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account
from db.postgres import get_db
from mt5.bridge import AccountCredentials, MT5Bridge

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{account_id}/info")
async def get_mt5_account_info(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login,
        password=password,
        server=account.server,
        path=account.mt5_path or settings.mt5_path,
    )

    # MT5 Python lib is a per-process singleton — only one mt5.initialize() at a time.
    # If a poller task is running for ANY account, opening a fresh MT5Bridge here would
    # call mt5.initialize() and drop the poller's COM connection.
    from services import mt5_poller
    poller_state = mt5_poller.get_states().get(account_id)
    any_poller_running = any(not t.done() for t in mt5_poller._tasks.values())

    if poller_state and poller_state.is_connected and poller_state.last_account_info:
        # Poller is up and has a fresh cache — serve from it (zero MT5 calls).
        logger.debug("MT5 info served from poller cache | account_id=%s", account_id)
        info = poller_state.last_account_info
    elif any_poller_running:
        # A poller task is active but hasn't finished its startup yet.
        # Don't open a competing bridge — the cache will be ready in seconds.
        raise HTTPException(
            status_code=503,
            detail="MT5 poller is initializing, please retry in a few seconds",
        )
    else:
        logger.info("Fetching MT5 info via fresh bridge | account_id=%s login=%s", account_id, account.login)
        try:
            async with MT5Bridge(creds) as bridge:
                info = await bridge.get_account_info()
        except RuntimeError as exc:
            logger.error("MT5 unavailable | account_id=%s | %s", account_id, exc)
            raise HTTPException(status_code=503, detail=str(exc))
        except ConnectionError as exc:
            logger.error("MT5 connection error | account_id=%s | %s", account_id, exc)
            raise HTTPException(status_code=502, detail=str(exc))

    if info is None:
        logger.error("MT5 returned no account info | account_id=%s login=%s", account_id, account.login)
        raise HTTPException(status_code=502, detail="MT5 connected but returned no account info")

    logger.info("MT5 info retrieved | account_id=%s balance=%.2f equity=%.2f", account_id, info.get("balance", 0), info.get("equity", 0))
    return {
        "login": info.get("login"),
        "name": info.get("name"),
        "server": info.get("server"),
        "company": info.get("company"),
        "currency": info.get("currency"),
        "leverage": info.get("leverage"),
        "balance": info.get("balance"),
        "equity": info.get("equity"),
        "margin": info.get("margin"),
        "margin_free": info.get("margin_free"),
        "margin_level": info.get("margin_level"),
        "profit": info.get("profit"),
        "trade_mode": info.get("trade_mode"),
    }


@router.get("/{account_id}/symbols", response_model=list[str])
async def list_symbols(
    account_id: int,
    all_symbols: bool = Query(False, description="Return all broker symbols, not just Market Watch"),
    db: AsyncSession = Depends(get_db),
):
    """Return symbol names available for this account's MT5 connection.

    By default returns only symbols currently visible in Market Watch.
    Pass ?all_symbols=true to see every symbol the broker offers.
    """
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login,
        password=password,
        server=account.server,
        path=account.mt5_path or settings.mt5_path,
    )
    try:
        async with MT5Bridge(creds) as bridge:
            symbols = await bridge.get_symbols(market_watch_only=not all_symbols)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (symbols) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (symbols) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return sorted(symbols)


