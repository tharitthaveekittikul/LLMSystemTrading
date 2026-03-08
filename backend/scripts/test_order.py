"""
Standalone MT5 Order Execution Test
=====================================
Bypasses the entire LLM pipeline so you can verify that MT5 connectivity,
filling-mode detection, and order execution all work — without paying LLM cost.

Usage (run from project root):
    cd backend
    python scripts/test_order.py

Config — edit the variables in the CONFIG section below.
"""

import asyncio
import logging
import sys
import os

# ── Ensure backend/ is on sys.path ──────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mt5.bridge import MT5Bridge, AccountCredentials
from mt5.executor import MT5Executor, OrderRequest

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("test_order")


# ════════════════════════════════════════════════════════════════════════════
# CONFIG — edit these before running
# ════════════════════════════════════════════════════════════════════════════
LOGIN    = 123456789          # your MT5 account number
PASSWORD = "your_password"    # plain-text for this test only
SERVER   = "ICMarkets-Demo"   # broker server name
MT5_PATH = ""                 # path to terminal64.exe — leave "" for default
SYMBOL   = "XAUUSDm"         # broker-specific symbol name (check MT5 Market Watch)

# When DRY_RUN = True: validates everything up to order_send but does NOT
# send a real order. Set to False to place a real (micro-lot) market order.
DRY_RUN  = True

# Order params — only used when DRY_RUN = False
# Use a price far from market so it gets rejected by the broker safely,
# or use realistic values on a demo account.
DIRECTION   = "BUY"
VOLUME      = 0.01         # minimum lot size (usually 0.01)
ENTRY_PRICE = 0.0          # 0.0 = will be replaced by live ask/bid below
STOP_LOSS   = 0.0          # 0.0 = will be set 50 pts below/above entry
TAKE_PROFIT = 0.0          # 0.0 = will be set 100 pts above/below entry
# ════════════════════════════════════════════════════════════════════════════


async def main() -> None:
    creds = AccountCredentials(
        login=LOGIN,
        password=PASSWORD,
        server=SERVER,
        path=MT5_PATH,
    )

    logger.info("=" * 60)
    logger.info("MT5 Order Execution Test")
    logger.info("  symbol   : %s", SYMBOL)
    logger.info("  dry_run  : %s", DRY_RUN)
    logger.info("  login    : %s @ %s", LOGIN, SERVER)
    logger.info("=" * 60)

    async with MT5Bridge(creds) as bridge:

        # ── 1. Account info ────────────────────────────────────────────────
        info = await bridge.get_account_info()
        if not info:
            logger.error("FAIL: could not get account info — check credentials")
            return
        logger.info(
            "✓ Account: %s  balance=%.2f %s  leverage=1:%s",
            info["login"], info["balance"], info["currency"], info["leverage"],
        )

        # ── 2. AutoTrading check ───────────────────────────────────────────
        auto_trade = await bridge.is_autotrading_enabled()
        if not auto_trade:
            logger.error(
                "FAIL: AutoTrading is DISABLED in the MT5 terminal. "
                "Enable it via the ▶ AutoTrading toolbar button."
            )
            return
        logger.info("✓ AutoTrading: ENABLED")

        # ── 3. Symbol info & filling mode ──────────────────────────────────
        filling_mode = await bridge.get_filling_mode(SYMBOL)
        filling_names = {0: "FOK", 1: "IOC", 2: "RETURN"}
        logger.info("✓ Filling mode for %s: %s (%s)", SYMBOL, filling_mode, filling_names.get(filling_mode, "?"))

        # ── 4. Live tick price ─────────────────────────────────────────────
        tick = await bridge.get_tick(SYMBOL)
        if not tick:
            logger.error("FAIL: could not get tick for %s", SYMBOL)
            return
        ask, bid = tick["ask"], tick["bid"]
        logger.info("✓ Tick: ask=%.5f  bid=%.5f", ask, bid)

        # ── 5. Derive order prices if not provided ─────────────────────────
        point = 0.01 if "XAU" in SYMBOL.upper() or "GOLD" in SYMBOL.upper() else 0.00001
        if DIRECTION == "BUY":
            entry  = ask if ENTRY_PRICE == 0 else ENTRY_PRICE
            sl     = round(entry - 50 * point, 5) if STOP_LOSS == 0 else STOP_LOSS
            tp     = round(entry + 100 * point, 5) if TAKE_PROFIT == 0 else TAKE_PROFIT
        else:
            entry  = bid if ENTRY_PRICE == 0 else ENTRY_PRICE
            sl     = round(entry + 50 * point, 5) if STOP_LOSS == 0 else STOP_LOSS
            tp     = round(entry - 100 * point, 5) if TAKE_PROFIT == 0 else TAKE_PROFIT

        logger.info(
            "Order: %s %s vol=%.2f  entry=%.5f  sl=%.5f  tp=%.5f",
            DIRECTION, SYMBOL, VOLUME, entry, sl, tp,
        )

        # ── 6. Place order ─────────────────────────────────────────────────
        order_request = OrderRequest(
            symbol=SYMBOL,
            action=DIRECTION,
            volume=VOLUME,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            comment="test_order_script",
        )

        executor = MT5Executor(bridge)
        result = await executor.place_order(order_request, dry_run=DRY_RUN)

        logger.info("=" * 60)
        if result.success:
            logger.info("✓ ORDER %s | ticket=%s  retcode=%s",
                        "SIMULATED" if DRY_RUN else "PLACED",
                        result.ticket, result.retcode)
        else:
            logger.error("✗ ORDER FAILED | error=%s  retcode=%s",
                         result.error, result.retcode)
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
