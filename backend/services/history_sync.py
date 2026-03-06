"""History Sync Service — fetch MT5 closed deals, sync to DB, format for analytics/AI.

Responsibilities:
- get_raw_deals: connect MT5, fetch deals list
- sync_to_db: upsert closed positions into trades table (skips existing tickets)
- get_performance_summary: compute win rate / profit factor from deal list
- format_for_llm: format recent trades as text for LLM prompt context
"""
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account, Trade
from mt5.bridge import AccountCredentials, MT5Bridge

logger = logging.getLogger(__name__)

# MT5 deal entry constants
_DEAL_ENTRY_IN = 0
_DEAL_ENTRY_OUT = 1

# MT5 deal type constants
_DEAL_TYPE_BUY = 0
_DEAL_TYPE_SELL = 1


class HistoryService:
    # ── Public async methods ──────────────────────────────────────────────

    async def get_raw_deals(self, account: Account, days: int) -> list[dict]:
        """Connect to MT5 and return all deals for the last `days` days."""
        date_to = datetime.now(UTC)
        date_from = date_to - timedelta(days=days)

        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            deals = await bridge.history_deals_get(date_from, date_to)

        logger.info(
            "Fetched %d deals | account_id=%s days=%s",
            len(deals), account.id, days,
        )
        return deals

    async def sync_to_db(
        self, account: Account, days: int, db: AsyncSession
    ) -> dict[str, int]:
        """Fetch MT5 deals and upsert closed positions into the trades table.

        Three cases per closed MT5 position:
        - No matching ticket → INSERT new row (source="manual").
        - Matching ticket with closed_at IS NULL → UPDATE close data.
          This handles AI trades placed by the system that were never marked closed.
        - Matching ticket already closed → skip (idempotent).

        Returns {"imported": N, "updated": U, "total_fetched": M}.
        """
        deals = await self.get_raw_deals(account, days)
        out_deals, in_by_pos = self._pair_deals(deals)

        imported = 0
        updated = 0
        try:
            for out_deal in out_deals:
                position_id: int = out_deal["position_id"]

                close_price = float(out_deal.get("price", 0.0))
                profit = (
                    float(out_deal.get("profit", 0.0))
                    + float(out_deal.get("commission", 0.0))
                    + float(out_deal.get("swap", 0.0))
                )
                closed_at = datetime.fromtimestamp(out_deal["time"], tz=UTC)

                existing = (
                    await db.execute(
                        select(Trade).where(
                            Trade.account_id == account.id,
                            Trade.ticket == position_id,
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    if existing.closed_at is not None:
                        continue  # already closed — skip
                    # Open AI/system trade: fill in the close data from MT5
                    existing.close_price = close_price
                    existing.profit = profit
                    existing.closed_at = closed_at
                    updated += 1
                    logger.debug(
                        "Closing open trade | account_id=%s ticket=%s profit=%s",
                        account.id, position_id, profit,
                    )
                    continue

                in_deal = in_by_pos.get(position_id)
                direction = (
                    "BUY"
                    if (in_deal and in_deal.get("type") == _DEAL_TYPE_BUY)
                    else "SELL"
                )
                entry_price = float(in_deal["price"]) if in_deal else 0.0
                if not in_deal:
                    logger.warning(
                        "No IN deal found for position_id=%s — entry_price=0.0, opened_at=now",
                        position_id,
                    )
                opened_at = (
                    datetime.fromtimestamp(in_deal["time"], tz=UTC)
                    if in_deal
                    else datetime.now(UTC)
                )

                trade = Trade(
                    account_id=account.id,
                    ticket=position_id,
                    symbol=out_deal.get("symbol", ""),
                    direction=direction,
                    volume=float(out_deal.get("volume", 0.0)),
                    entry_price=entry_price,
                    stop_loss=0.0,
                    take_profit=0.0,
                    close_price=close_price,
                    profit=profit,
                    opened_at=opened_at,
                    closed_at=closed_at,
                    source="manual",
                    is_paper_trade=False,
                )
                db.add(trade)
                imported += 1

            if imported or updated:
                await db.commit()
                logger.info(
                    "History sync complete | account_id=%s imported=%s updated=%s",
                    account.id, imported, updated,
                )
        except Exception:
            await db.rollback()
            logger.error("sync_to_db failed — rolled back | account_id=%s", account.id, exc_info=True)
            raise

        return {"imported": imported, "updated": updated, "total_fetched": len(deals)}

    # ── Pure helper methods (no I/O) ──────────────────────────────────────

    @staticmethod
    def _pair_deals(
        deals: list[dict],
    ) -> tuple[list[dict], dict[int, dict]]:
        """Split deals into OUT deals and a position_id→IN deal lookup.

        Returns (out_deals, in_deals_by_position_id).
        Only fully-closed positions (entry==DEAL_ENTRY_OUT) are returned
        in out_deals. Partially-closed (DEAL_ENTRY_INOUT) are treated as OUT.
        """
        out_deals: list[dict] = []
        in_by_pos: dict[int, dict] = {}

        for deal in deals:
            entry = deal.get("entry", -1)
            pos_id = deal.get("position_id", 0)
            if entry == _DEAL_ENTRY_IN:
                if pos_id in in_by_pos:
                    logger.warning(
                        "Multiple IN deals for position_id=%s (scaled-in position) — using first entry",
                        pos_id,
                    )
                else:
                    in_by_pos[pos_id] = deal
            elif entry == _DEAL_ENTRY_OUT or entry == 2:  # 2 = DEAL_ENTRY_INOUT
                out_deals.append(deal)

        return out_deals, in_by_pos

    @staticmethod
    def get_performance_summary(deals: list[dict]) -> dict[str, Any]:
        """Compute win rate, P&L, and profit factor from a deal list.

        Only OUT deals (entry==1) contribute to stats.
        """
        out_deals = [d for d in deals if d.get("entry") in (_DEAL_ENTRY_OUT, 2)]
        if not out_deals:
            return {
                "trade_count": 0,
                "winning_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
            }

        profits = [
            float(d.get("profit", 0.0))
            + float(d.get("commission", 0.0))
            + float(d.get("swap", 0.0))
            for d in out_deals
        ]
        winning = [p for p in profits if p > 0]
        losing = [p for p in profits if p < 0]
        gross_profit = sum(winning)
        gross_loss = abs(sum(losing))
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else math.inf
        )

        return {
            "trade_count": len(out_deals),
            "winning_trades": len(winning),
            "win_rate": round(len(winning) / len(out_deals), 4),
            "total_pnl": round(sum(profits), 2),
            "profit_factor": round(profit_factor, 2) if not math.isinf(profit_factor) else math.inf,
        }

    @staticmethod
    def format_for_llm(
        out_deals: list[dict],
        in_by_pos: dict[int, dict],
        limit: int = 10,
    ) -> str:
        """Return a compact text block of the N most recent closed trades.

        Intended for injection into the LLM prompt as additional context.
        Returns empty string if no deals.
        """
        if not out_deals:
            return ""

        recent = sorted(out_deals, key=lambda d: d.get("time", 0), reverse=True)[:limit]
        lines = [f"Recent closed trades (last {limit}):"]
        for d in recent:
            pos_id = d.get("position_id", 0)
            in_deal = in_by_pos.get(pos_id)
            direction = (
                "BUY"
                if (in_deal and in_deal.get("type") == _DEAL_TYPE_BUY)
                else "SELL"
            )
            profit = (
                float(d.get("profit", 0.0))
                + float(d.get("commission", 0.0))
                + float(d.get("swap", 0.0))
            )
            sign = "+" if profit >= 0 else ""
            symbol = d.get("symbol", "?")
            volume = d.get("volume", "?")
            ts = d.get("time", 0)
            date_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d") if ts else "?"
            lines.append(
                f"  - {symbol} {direction} {volume} lot | profit={sign}{profit:.2f} | {date_str}"
            )
        return "\n".join(lines)
