import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt, encrypt
from db.models import Account
from db.postgres import AsyncSessionLocal, get_db
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
    imported: int = Field(..., description="Number of new trades inserted into the database")
    updated: int = Field(0, description="Number of existing open trades closed by this sync")
    total_fetched: int = Field(..., description="Total deals returned by MT5 before deduplication")


class ResearchCycleTrade(BaseModel):
    id: int
    symbol: str
    direction: str
    profit: float
    closed_at: str | None
    excluded: bool = False


class ResearchProgressResponse(BaseModel):
    closed_trades: int = Field(..., description="Total closed trades for this account (profit != 0)")
    cycle_progress: int = Field(..., description="Trades since last successful run (can exceed 30 if research failed)")
    remaining: int = Field(..., description="Trades until the next research loop fires (0 means ready)")
    last_run_at: str | None = Field(None, description="ISO timestamp of the last research loop run")
    just_completed: bool = Field(False, description="True when cycle_progress==0 and a loop has run")
    cycle_trades: list[ResearchCycleTrade] = Field(default_factory=list, description="Trades in the current cycle")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.is_active))
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


# MT5 order state / deal entry constants
_ORDER_STATE_CANCELED  = 2
_ORDER_STATE_FILLED    = 4
_ORDER_STATE_REJECTED  = 5
_ORDER_STATE_EXPIRED   = 6
_DEAL_ENTRY_OUT        = 1   # closing deal


class SyncOrdersResponse(BaseModel):
    total_checked: int
    positions_closed: int   # open positions manually closed in MT5
    orders_cancelled: int   # pending orders cancelled/expired in MT5
    unchanged: int


@router.post("/{account_id}/sync-orders", response_model=SyncOrdersResponse)
async def sync_orders(account_id: int, db: AsyncSession = Depends(get_db)):
    """Reconcile DB open trades against MT5.

    Handles two cases:
    1. Pending orders (order_status='pending') cancelled/expired in MT5.
    2. Filled positions (order_status='filled') manually closed in MT5.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    from db.models import Trade

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

    # ── Load ALL open DB trades (pending + filled) ────────────────────────────
    result = await db.execute(
        select(Trade).where(
            Trade.account_id == account_id,
            Trade.closed_at.is_(None),
        )
    )
    open_trades: list[Trade] = list(result.scalars().all())

    if not open_trades:
        return SyncOrdersResponse(total_checked=0, positions_closed=0, orders_cancelled=0, unchanged=0)

    oldest_opened = min(t.opened_at for t in open_trades)
    now = datetime.now(timezone.utc)
    hist_end = now + timedelta(seconds=30)  # buffer: include deals closed in the current second

    try:
        async with MT5Bridge(creds) as bridge:
            active_positions = await bridge.get_positions()
            active_orders    = await bridge.get_orders()
            hist_orders      = await bridge.history_orders_get(oldest_opened, hist_end)
            hist_deals       = await bridge.history_deals_get(oldest_opened, hist_end)

    except RuntimeError as exc:
        logger.error("MT5 unavailable (sync-orders) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (sync-orders) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    active_position_tickets: set[int] = {p["ticket"] for p in active_positions}
    active_order_tickets: set[int]    = {o["ticket"] for o in active_orders}
    hist_orders_by_ticket: dict[int, dict] = {o["ticket"]: o for o in hist_orders}

    # Closing deals indexed by position_id (entry=OUT means the position was closed)
    closing_deals: dict[int, dict] = {
        d["position_id"]: d
        for d in hist_deals
        if d.get("entry") == _DEAL_ENTRY_OUT
    }

    counts = {"positions_closed": 0, "orders_cancelled": 0, "unchanged": 0}
    now_ts = datetime.now(timezone.utc)
    newly_closed_trade_ids: list[int] = []

    for trade in open_trades:
        # ── Case 1: filled position ───────────────────────────────────────────
        if trade.order_status == "filled":
            if trade.ticket in active_position_tickets:
                counts["unchanged"] += 1
                continue

            # Position no longer active — resolve position ticket then find closing deal.
            # trade.ticket stores the order ticket from order_send(); in MT5 hedging mode
            # the position ticket equals the order ticket, but hist_orders["position_id"]
            # is the authoritative source.
            hist_order = hist_orders_by_ticket.get(trade.ticket)
            position_ticket = (
                hist_order.get("position_id") or trade.ticket
            ) if hist_order else trade.ticket
            deal = closing_deals.get(position_ticket) or closing_deals.get(trade.ticket)
            if deal:
                deal_time = deal.get("time")
                trade.close_price = deal.get("price")
                trade.profit      = deal.get("profit")
                trade.closed_at   = (
                    datetime.fromtimestamp(deal_time, tz=timezone.utc)
                    if deal_time else now_ts
                )
            else:
                trade.closed_at = now_ts  # fallback: no deal found
                logger.warning(
                    "No closing deal found | account_id=%s ticket=%s position_ticket=%s total_deals=%s",
                    account_id, trade.ticket, position_ticket, len(hist_deals),
                )

            newly_closed_trade_ids.append(trade.id)
            counts["positions_closed"] += 1
            logger.info(
                "Position closed | account_id=%s ticket=%s position_ticket=%s close_price=%s profit=%s",
                account_id, trade.ticket, position_ticket, trade.close_price, trade.profit,
            )

        # ── Case 2: pending order ─────────────────────────────────────────────
        else:
            if trade.ticket in active_order_tickets:
                counts["unchanged"] += 1
                continue

            hist_order = hist_orders_by_ticket.get(trade.ticket)
            state = hist_order.get("state") if hist_order else None

            if state == _ORDER_STATE_FILLED:
                # Pending order filled → a position was opened (may have been closed since)
                position_ticket = (hist_order.get("position_id") or trade.ticket) if hist_order else trade.ticket
                if position_ticket in active_position_tickets:
                    # Position still open — upgrade status, leave closed_at=None
                    trade.order_status = "filled"
                    counts["unchanged"] += 1
                    logger.info(
                        "Pending order filled, position open | account_id=%s ticket=%s position=%s",
                        account_id, trade.ticket, position_ticket,
                    )
                    continue
                # Position was closed (SL / TP / manual)
                trade.order_status = "filled"
                deal = closing_deals.get(position_ticket)
                if deal:
                    deal_time = deal.get("time")
                    trade.close_price = deal.get("price")
                    trade.profit      = deal.get("profit")
                    trade.closed_at   = (
                        datetime.fromtimestamp(deal_time, tz=timezone.utc)
                        if deal_time else now_ts
                    )
                else:
                    trade.closed_at = now_ts
                newly_closed_trade_ids.append(trade.id)
                counts["positions_closed"] += 1
                logger.info(
                    "Pending order filled+closed | account_id=%s ticket=%s position=%s close_price=%s profit=%s",
                    account_id, trade.ticket, position_ticket, trade.close_price, trade.profit,
                )

            elif state == _ORDER_STATE_EXPIRED:
                trade.order_status = "expired"
                trade.closed_at = now_ts
                counts["orders_cancelled"] += 1
                logger.info(
                    "Pending order reconciled | account_id=%s ticket=%s state=%s -> expired",
                    account_id, trade.ticket, state,
                )
            else:
                trade.order_status = "cancelled"
                trade.closed_at = now_ts
                counts["orders_cancelled"] += 1
                logger.info(
                    "Pending order reconciled | account_id=%s ticket=%s state=%s -> cancelled",
                    account_id, trade.ticket, state,
                )

    await db.commit()

    # ── Post-trade analysis + research loop (fire-and-forget) ────────────────
    if newly_closed_trade_ids:
        import asyncio

        from db.postgres import AsyncSessionLocal
        from services.research_loop import maybe_run
        from services.trade_analyzer import analyze_closed_trade
        for tid in newly_closed_trade_ids:
            asyncio.ensure_future(analyze_closed_trade(tid))

        _n_closed = len(newly_closed_trade_ids)
        _acct_id = account_id

        async def _research_loop_task() -> None:
            async with AsyncSessionLocal() as _sess:
                await maybe_run(_acct_id, _sess, _n_closed)

        asyncio.ensure_future(_research_loop_task())

    return SyncOrdersResponse(
        total_checked=len(open_trades),
        positions_closed=counts["positions_closed"],
        orders_cancelled=counts["orders_cancelled"],
        unchanged=counts["unchanged"],
    )


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

    # ── Fire post-trade analysis for newly imported/updated trades ────────────
    new_ids: list[int] = result.get("new_trade_ids", [])
    if new_ids:
        import asyncio

        from services.trade_analyzer import analyze_closed_trade
        for tid in new_ids:
            asyncio.ensure_future(analyze_closed_trade(tid))
        logger.info("Post-trade analysis queued | account_id=%s count=%s", account_id, len(new_ids))

    return result


class FullSyncResponse(BaseModel):
    # Phase 1 — reconcile open DB trades against MT5 live state
    positions_closed: int = Field(0, description="Filled positions no longer active in MT5 (TP/SL/manual close)")
    orders_expired: int = Field(0, description="Pending orders expired in MT5")
    orders_cancelled: int = Field(0, description="Pending orders cancelled/rejected in MT5")
    unchanged: int = Field(0, description="Open trades still active in MT5")
    # Phase 2 — import closed deals not yet in DB (manually placed in MT5 terminal)
    newly_imported: int = Field(0, description="Closed deals imported from MT5 history (manual terminal trades)")
    updated: int = Field(0, description="Open AI trades closed by history import")
    # Totals
    total_checked: int = Field(0, description="Total open DB trades checked in phase 1")


@router.post("/{account_id}/sync", response_model=FullSyncResponse)
async def sync_account(account_id: int, db: AsyncSession = Depends(get_db)):
    """Unified sync — one button covers all cases.

    Phase 1 (sync-orders): reconcile all open DB trades against MT5 live state.
      Handles: pending orders expired/cancelled, filled positions closed via TP/SL or manually.
    Phase 2 (history backfill): import any closed deals from the last 30 days that are
      not yet in the DB — catches orders placed directly in the MT5 terminal.

    Post-trade analysis is fired for all newly closed non-manual trades.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    from db.models import Trade

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

    # ── Load ALL open DB trades (pending + filled) ────────────────────────────
    result = await db.execute(
        select(Trade).where(
            Trade.account_id == account_id,
            Trade.closed_at.is_(None),
        )
    )
    open_trades: list[Trade] = list(result.scalars().all())

    oldest_opened = min((t.opened_at for t in open_trades), default=None)
    now = datetime.now(timezone.utc)
    hist_start = oldest_opened if oldest_opened else (now - timedelta(days=30))
    hist_end = now + timedelta(seconds=30)
    # Phase 2 always covers at least the last 30 days to catch manual terminal trades
    backfill_from = min(hist_start, now - timedelta(days=30))

    try:
        async with MT5Bridge(creds) as bridge:
            active_positions = await bridge.get_positions()
            active_orders    = await bridge.get_orders()
            hist_orders      = await bridge.history_orders_get(hist_start, hist_end) if open_trades else []
            hist_deals       = await bridge.history_deals_get(backfill_from, hist_end)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (sync) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (sync) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    active_position_tickets: set[int] = {p["ticket"] for p in active_positions}
    active_order_tickets: set[int]    = {o["ticket"] for o in active_orders}
    hist_orders_by_ticket: dict[int, dict] = {o["ticket"]: o for o in hist_orders}
    closing_deals: dict[int, dict] = {
        d["position_id"]: d
        for d in hist_deals
        if d.get("entry") == _DEAL_ENTRY_OUT
    }

    counts = {"positions_closed": 0, "orders_expired": 0, "orders_cancelled": 0, "unchanged": 0}
    now_ts = datetime.now(timezone.utc)
    newly_closed_trade_ids: list[int] = []

    # ── Phase 1: reconcile open DB trades ─────────────────────────────────────
    for trade in open_trades:
        if trade.order_status == "filled":
            if trade.ticket in active_position_tickets:
                counts["unchanged"] += 1
                continue

            hist_order = hist_orders_by_ticket.get(trade.ticket)
            position_ticket = (
                hist_order.get("position_id") or trade.ticket
            ) if hist_order else trade.ticket
            deal = closing_deals.get(position_ticket) or closing_deals.get(trade.ticket)
            if deal:
                deal_time = deal.get("time")
                trade.close_price = deal.get("price")
                trade.profit      = deal.get("profit")
                trade.closed_at   = (
                    datetime.fromtimestamp(deal_time, tz=timezone.utc)
                    if deal_time else now_ts
                )
            else:
                trade.closed_at = now_ts
                logger.warning(
                    "No closing deal found | account_id=%s ticket=%s position_ticket=%s",
                    account_id, trade.ticket, position_ticket,
                )

            newly_closed_trade_ids.append(trade.id)
            counts["positions_closed"] += 1
            logger.info(
                "Position closed | account_id=%s ticket=%s close_price=%s profit=%s",
                account_id, trade.ticket, trade.close_price, trade.profit,
            )

        else:  # pending order
            if trade.ticket in active_order_tickets:
                counts["unchanged"] += 1
                continue

            hist_order = hist_orders_by_ticket.get(trade.ticket)
            state = hist_order.get("state") if hist_order else None

            if state == _ORDER_STATE_FILLED:
                position_ticket = (hist_order.get("position_id") or trade.ticket) if hist_order else trade.ticket
                if position_ticket in active_position_tickets:
                    trade.order_status = "filled"
                    counts["unchanged"] += 1
                    continue
                trade.order_status = "filled"
                deal = closing_deals.get(position_ticket)
                if deal:
                    deal_time = deal.get("time")
                    trade.close_price = deal.get("price")
                    trade.profit      = deal.get("profit")
                    trade.closed_at   = (
                        datetime.fromtimestamp(deal_time, tz=timezone.utc)
                        if deal_time else now_ts
                    )
                else:
                    trade.closed_at = now_ts
                newly_closed_trade_ids.append(trade.id)
                counts["positions_closed"] += 1
                logger.info(
                    "Pending order filled+closed | account_id=%s ticket=%s profit=%s",
                    account_id, trade.ticket, trade.profit,
                )

            elif state == _ORDER_STATE_EXPIRED:
                trade.order_status = "expired"
                trade.closed_at = now_ts
                counts["orders_expired"] += 1
                logger.info("Order expired | account_id=%s ticket=%s", account_id, trade.ticket)

            else:
                trade.order_status = "cancelled"
                trade.closed_at = now_ts
                counts["orders_cancelled"] += 1
                logger.info("Order cancelled | account_id=%s ticket=%s state=%s", account_id, trade.ticket, state)

    await db.commit()

    # ── Phase 2: backfill closed deals not yet in DB ──────────────────────────
    svc = HistoryService()
    backfill = await svc.sync_deals_to_db(account, hist_deals, db)
    newly_imported = backfill["imported"]
    updated = backfill["updated"]
    backfill_ids: list[int] = backfill.get("new_trade_ids", [])

    # ── Post-trade analysis (fire-and-forget, skip manual terminal trades) ────
    all_new_ids = newly_closed_trade_ids + [
        tid for tid in backfill_ids if tid not in newly_closed_trade_ids
    ]
    if all_new_ids:
        import asyncio

        from services.research_loop import maybe_run
        from services.trade_analyzer import analyze_closed_trade

        # Only analyze system-placed trades (source != "manual")
        result2 = await db.execute(
            select(Trade).where(
                Trade.id.in_(all_new_ids),
                Trade.source != "manual",
            )
        )
        system_trade_ids = [t.id for t in result2.scalars().all()]
        for tid in system_trade_ids:
            asyncio.ensure_future(analyze_closed_trade(tid))

        if system_trade_ids:
            _n = len(system_trade_ids)
            _acct = account_id

            async def _research_task() -> None:
                async with AsyncSessionLocal() as _sess:
                    await maybe_run(_acct, _sess, _n)

            asyncio.ensure_future(_research_task())
            logger.info("Post-trade analysis queued | account_id=%s count=%s", account_id, len(system_trade_ids))

    logger.info(
        "Full sync complete | account_id=%s phase1_closed=%s expired=%s cancelled=%s "
        "phase2_imported=%s updated=%s unchanged=%s",
        account_id,
        counts["positions_closed"], counts["orders_expired"], counts["orders_cancelled"],
        newly_imported, updated, counts["unchanged"],
    )

    return FullSyncResponse(
        positions_closed=counts["positions_closed"],
        orders_expired=counts["orders_expired"],
        orders_cancelled=counts["orders_cancelled"],
        unchanged=counts["unchanged"],
        newly_imported=newly_imported,
        updated=updated,
        total_checked=len(open_trades),
    )


class SyncAllResponse(BaseModel):
    imported: int
    updated: int = 0
    total_fetched: int
    accounts_synced: int
    errors: list[str]


@router.post("/sync-all", response_model=SyncAllResponse)
async def sync_all_accounts(
    days: int = Query(90, ge=1, le=3650, description="Number of days to sync per account"),
    db: AsyncSession = Depends(get_db),
):
    """Sync MT5 history for all active accounts into the local trades table.

    Each account gets its own DB session so a single MT5 failure cannot roll
    back another account's already-committed trades.
    Returns aggregate counts and a list of per-account error strings.
    """
    result = await db.execute(select(Account).where(Account.is_active == True))  # noqa: E712
    accounts = result.scalars().all()

    total_imported = 0
    total_updated = 0
    total_fetched = 0
    errors: list[str] = []
    svc = HistoryService()

    for account in accounts:
        async with AsyncSessionLocal() as session:
            try:
                r = await svc.sync_to_db(account, days, session)
                total_imported += r["imported"]
                total_updated += r["updated"]
                total_fetched += r["total_fetched"]
            except (RuntimeError, ConnectionError) as exc:
                errors.append(f"Account {account.id} ({account.name}): {exc}")
                logger.warning(
                    "sync-all: skipped account_id=%s | %s", account.id, exc
                )
            except Exception as exc:
                errors.append(f"Account {account.id} ({account.name}): {exc}")
                logger.error(
                    "sync-all: unexpected error account_id=%s", account.id, exc_info=True
                )

    logger.info(
        "sync-all complete | accounts=%s imported=%s updated=%s total=%s errors=%s",
        len(accounts), total_imported, total_updated, total_fetched, len(errors),
    )
    return SyncAllResponse(
        imported=total_imported,
        updated=total_updated,
        total_fetched=total_fetched,
        accounts_synced=len(accounts) - len(errors),
        errors=errors,
    )


class EquityPoint(BaseModel):
    ts: str
    equity: float
    balance: float


@router.get("/{account_id}/equity-history", response_model=list[EquityPoint])
async def get_equity_history(
    account_id: int,
    hours: int = Query(24, ge=0, le=8760),
    db: AsyncSession = Depends(get_db),
):
    """Return equity snapshots for the last N hours (default 24). Empty list if QuestDB unavailable."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.questdb import get_equity_history
    points = await get_equity_history(account_id=account_id, hours=hours)
    return points


@router.get("/{account_id}/research-progress", response_model=ResearchProgressResponse)
async def get_research_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return the current 30-trade research loop progress for an account."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from services.research_loop import RESEARCH_EVERY, _count_closed_trades, read_config
    closed_trades = await _count_closed_trades(db, account_id)
    config = read_config()
    last_run_at: str | None = config.get("last_run_at")
    last_run_count: int = config.get("trade_count_at_run", 0)
    cycle_progress = max(closed_trades - last_run_count, 0)  # clamp: old configs may have stored total count
    remaining = max(RESEARCH_EVERY - cycle_progress, 0)
    just_completed = cycle_progress == 0 and last_run_at is not None

    # Fetch trades in the current cycle (since last successful run)
    last_trade_id_at_run: int = config.get("last_trade_id_at_run", 0)
    cycle_trades: list[ResearchCycleTrade] = []
    if cycle_progress > 0 or last_trade_id_at_run:
        from sqlalchemy import select

        from db.models import Trade
        base_where = [Trade.account_id == account_id, Trade.closed_at.is_not(None), Trade.profit != 0]
        if last_trade_id_at_run:
            base_where.append(Trade.id > last_trade_id_at_run)
        rows = (
            await db.execute(
                select(Trade.id, Trade.symbol, Trade.direction, Trade.profit, Trade.closed_at, Trade.exclude_from_research)
                .where(*base_where)
                .order_by(Trade.closed_at.desc())
                .limit(cycle_progress if not last_trade_id_at_run else None)
            )
        ).all()
        cycle_trades = [
            ResearchCycleTrade(
                id=r.id,
                symbol=r.symbol,
                direction=r.direction or "—",
                profit=float(r.profit or 0),
                closed_at=r.closed_at.isoformat() if r.closed_at else None,
                excluded=bool(r.exclude_from_research),
            )
            for r in rows
        ]

    return ResearchProgressResponse(
        closed_trades=closed_trades,
        cycle_progress=cycle_progress,
        remaining=remaining,
        last_run_at=last_run_at,
        just_completed=just_completed,
        cycle_trades=cycle_trades,
    )


@router.post("/{account_id}/research-loop/trigger", status_code=200)
async def trigger_research_loop(account_id: int, db: AsyncSession = Depends(get_db)):
    """Manually trigger the research loop for an account (forced run)."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from services.research_loop import run
    try:
        await run(account_id, db)
        from services.research_loop import read_config
        config = read_config()
        return {"status": "ok", "last_run_at": config.get("last_run_at")}
    except Exception as exc:
        logger.exception("Manual research loop trigger failed | account_id=%s", account_id)
        raise HTTPException(status_code=500, detail=f"Research loop failed: {exc}") from exc


@router.post("/{account_id}/research-progress/trades/{trade_id}/toggle-exclude", status_code=200)
async def toggle_exclude_research_trade(account_id: int, trade_id: int, db: AsyncSession = Depends(get_db)):
    """Toggle exclude_from_research flag on a trade. Excluded trades are skipped by the research loop."""
    from db.models import Trade
    trade = await db.get(Trade, trade_id)
    if not trade or trade.account_id != account_id:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.exclude_from_research = not trade.exclude_from_research
    await db.commit()
    return {"id": trade_id, "excluded": trade.exclude_from_research}


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
