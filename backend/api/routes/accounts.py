import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt, encrypt
from db.models import Account
from db.postgres import get_db
from mt5.bridge import AccountCredentials, MT5Bridge
from services.history_sync import HistoryService

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request / Response schemas ────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    broker: str = Field(..., min_length=1, max_length=100)
    login: int = Field(..., gt=0, description="MT5 account login number")
    password: str = Field(..., min_length=1)
    server: str = Field(..., min_length=1, max_length=200)
    is_live: bool = False
    allowed_symbols: list[str] = []
    max_lot_size: float = Field(default=0.1, gt=0.0, le=100.0)
    risk_pct: float = Field(default=0.01, gt=0.0, le=1.0, description="Fraction of balance to risk per trade (0.01 = 1%)")
    auto_trade_enabled: bool = True
    mt5_path: str = Field(default="", max_length=500)
    account_type: Literal["USD", "USC"] = "USD"


class AccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    broker: str | None = Field(None, min_length=1, max_length=100)
    server: str | None = Field(None, min_length=1, max_length=200)
    is_live: bool | None = None
    max_lot_size: float | None = Field(None, gt=0.0, le=100.0)
    risk_pct: float | None = Field(None, gt=0.0, le=1.0, description="Fraction of balance to risk per trade (0.01 = 1%)")
    auto_trade_enabled: bool | None = None
    password: str | None = Field(None, min_length=1, description="Leave empty to keep existing password")
    mt5_path: str | None = Field(None, max_length=500, description="Path to terminal64.exe for this account. Leave empty to use global MT5_PATH.")
    account_type: Literal["USD", "USC"] | None = None


class AccountResponse(BaseModel):
    id: int
    name: str
    broker: str
    login: int
    server: str
    is_live: bool
    is_active: bool
    allowed_symbols: list[str]
    max_lot_size: float
    risk_pct: float
    auto_trade_enabled: bool = True
    mt5_path: str
    account_type: str
    created_at: datetime


class HistorySyncResponse(BaseModel):
    imported: int = Field(..., description="Number of new trades written to the database")
    total_fetched: int = Field(..., description="Total deals returned by MT5 before deduplication")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.is_active == True))
    accounts = result.scalars().all()
    return [_to_response(a) for a in accounts]


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db)):
    logger.info("Creating account | broker=%s login=%s is_live=%s", payload.broker, payload.login, payload.is_live)
    account = Account(
        name=payload.name,
        broker=payload.broker,
        login=payload.login,
        password_encrypted=encrypt(payload.password),
        server=payload.server,
        is_live=payload.is_live,
        allowed_symbols=json.dumps(payload.allowed_symbols),
        max_lot_size=payload.max_lot_size,
        risk_pct=payload.risk_pct,
        auto_trade_enabled=payload.auto_trade_enabled,
        mt5_path=payload.mt5_path,
        account_type=payload.account_type,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    logger.info("Account created | id=%s broker=%s login=%s", account.id, account.broker, account.login)
    return _to_response(account)


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")
    return _to_response(account)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(account_id: int, payload: AccountUpdate, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    if payload.name is not None:
        account.name = payload.name
    if payload.broker is not None:
        account.broker = payload.broker
    if payload.server is not None:
        account.server = payload.server
    if payload.is_live is not None:
        account.is_live = payload.is_live
    if payload.max_lot_size is not None:
        account.max_lot_size = payload.max_lot_size
    if payload.risk_pct is not None:
        account.risk_pct = payload.risk_pct
    if payload.auto_trade_enabled is not None:
        account.auto_trade_enabled = payload.auto_trade_enabled
    if payload.password is not None:
        account.password_encrypted = encrypt(payload.password)
    if payload.mt5_path is not None:
        account.mt5_path = payload.mt5_path
    if payload.account_type is not None:
        account.account_type = payload.account_type

    await db.commit()
    await db.refresh(account)
    logger.info("Account updated | id=%s", account_id)
    return _to_response(account)


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

    logger.info("Fetching MT5 info | account_id=%s login=%s", account_id, account.login)
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


@router.delete("/{account_id}", status_code=204)
async def deactivate_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = False
    await db.commit()
    logger.info("Account deactivated | id=%s", account_id)


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


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    timeframe: str = Field(default="M15", pattern=r"^(M1|M5|M15|M30|H1|H4|D1|W1)$")


class AnalyzeResponse(BaseModel):
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    rationale: str
    timeframe: str
    order_placed: bool
    ticket: int | None
    journal_id: int


@router.post("/{account_id}/analyze", response_model=AnalyzeResponse)
async def analyze_account(
    account_id: int,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run LLM market analysis and conditionally execute a trade.

    Returns the signal plus whether an order was placed.
    Errors: 404 account not found, 429 rate limited, 502/503 MT5 unavailable.
    """
    from services.ai_trading import AITradingService

    service = AITradingService()
    result = await service.analyze_and_trade(
        account_id=account_id,
        symbol=body.symbol,
        timeframe=body.timeframe,
        db=db,
    )
    return AnalyzeResponse(
        action=result.signal.action,
        entry=result.signal.entry,
        stop_loss=result.signal.stop_loss,
        take_profit=result.signal.take_profit,
        confidence=result.signal.confidence,
        rationale=result.signal.rationale,
        timeframe=result.signal.timeframe,
        order_placed=result.order_placed,
        ticket=result.ticket,
        journal_id=result.journal_id,
    )


class AccountStatsResponse(BaseModel):
    win_rate: float
    total_pnl: float
    trade_count: int
    winning_trades: int


@router.get("/{account_id}/stats", response_model=AccountStatsResponse)
async def get_account_stats(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return aggregated trade statistics for an account (closed trades only)."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.models import Trade

    result = await db.execute(
        select(
            func.count(Trade.id).label("trade_count"),
            func.coalesce(func.sum(Trade.profit), 0.0).label("total_pnl"),
            func.count(Trade.id).filter(Trade.profit > 0).label("winning_trades"),
        ).where(
            Trade.account_id == account_id,
            Trade.closed_at.is_not(None),
        )
    )
    row = result.one()
    trade_count = row.trade_count or 0
    winning_trades = row.winning_trades or 0
    win_rate = winning_trades / trade_count if trade_count > 0 else 0.0

    return AccountStatsResponse(
        win_rate=round(win_rate, 4),
        total_pnl=round(float(row.total_pnl), 2),
        trade_count=trade_count,
        winning_trades=winning_trades,
    )


@router.get("/{account_id}/history", response_model=list[dict])
async def get_account_history(
    account_id: int,
    days: int = Query(90, ge=1, le=3650, description="Number of days of history to fetch"),
    db: AsyncSession = Depends(get_db),
):
    """Return raw MT5 closed deals for the last N days.

    Each item is one deal dict from MT5. Use this for dashboard charts and analytics.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    logger.info("Fetching MT5 history | account_id=%s days=%s", account_id, days)
    try:
        svc = HistoryService()
        deals = await svc.get_raw_deals(account, days)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (history) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (history) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return deals


@router.post("/{account_id}/history/sync", response_model=HistorySyncResponse)
async def sync_account_history(
    account_id: int,
    days: int = Query(90, ge=1, le=3650, description="Number of days to sync"),
    db: AsyncSession = Depends(get_db),
):
    """Sync MT5 closed trades into the local trades table.

    Skips trades already present (idempotent). Returns count of newly imported rows.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    logger.info("Syncing MT5 history | account_id=%s days=%s", account_id, days)
    try:
        svc = HistoryService()
        result = await svc.sync_to_db(account, days, db)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (sync) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (sync) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    logger.info(
        "History sync complete | account_id=%s imported=%s total=%s",
        account_id, result["imported"], result["total_fetched"],
    )
    return result


class EquityPoint(BaseModel):
    ts: str
    equity: float
    balance: float


@router.get("/{account_id}/equity-history", response_model=list[EquityPoint])
async def get_equity_history(
    account_id: int,
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    """Return equity snapshots for the last N hours (default 24). Empty list if QuestDB unavailable."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.questdb import get_equity_history
    points = await get_equity_history(account_id=account_id, hours=hours)
    return points


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_symbols(raw: str) -> list[str]:
    try:
        return json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []


def _to_response(a: Account) -> AccountResponse:
    return AccountResponse(
        id=a.id,
        name=a.name,
        broker=a.broker,
        login=a.login,
        server=a.server,
        is_live=a.is_live,
        is_active=a.is_active,
        allowed_symbols=_parse_symbols(a.allowed_symbols),
        max_lot_size=a.max_lot_size,
        risk_pct=a.risk_pct,
        auto_trade_enabled=a.auto_trade_enabled,
        mt5_path=a.mt5_path or "",
        account_type=a.account_type or "USD",
        created_at=a.created_at,
    )
