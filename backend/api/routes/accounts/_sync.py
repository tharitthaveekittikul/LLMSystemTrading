"""Reconciliation between DB trade state and live MT5 broker state.

sync_orders / sync_account_history / sync_account operate on a single
account; sync_all_accounts fans out sync_account across every active
account.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.accounts._schemas import (
    FullSyncResponse,
    HistorySyncResponse,
    SyncAllResponse,
    SyncOrdersResponse,
)
from core.config import settings
from core.security import decrypt
from db.models import Account, Trade
from db.postgres import AsyncSessionLocal, get_db
from mt5.bridge import AccountCredentials, MT5Bridge
from services.history_sync import HistoryService

router = APIRouter()
logger = logging.getLogger(__name__)

# MT5 order state / deal entry constants
_ORDER_STATE_CANCELED  = 2
_ORDER_STATE_FILLED    = 4
_ORDER_STATE_REJECTED  = 5
_ORDER_STATE_EXPIRED   = 6
_DEAL_ENTRY_OUT        = 1   # closing deal


@router.post("/{account_id}/sync-orders", response_model=SyncOrdersResponse)
async def sync_orders(account_id: int, db: AsyncSession = Depends(get_db)):
    """Reconcile DB open trades against MT5.

    Handles two cases:
    1. Pending orders (order_status='pending') cancelled/expired in MT5.
    2. Filled positions (order_status='filled') manually closed in MT5.
    Errors: 404 account not found, 502/503 MT5 unavailable.
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


