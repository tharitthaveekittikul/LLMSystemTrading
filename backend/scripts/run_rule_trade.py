import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import AsyncSessionLocal
from db.models import Account, Strategy
from services.ai_trading import AITradingService
from strategies.ema_atr_breakout import EmaAtrBreakout

# Configure basic logging for the script
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting Run Rule Trade Script")

    async with AsyncSessionLocal() as db:
        # 1. Fetch the first active account
        account_result = await db.execute(
            select(Account).where(Account.is_active.is_(True)).limit(1)
        )
        account = account_result.scalar_one_or_none()

        if not account:
            logger.error("No active account found. Cannot execute trade.")
            return

        logger.info(f"Using Account ID: {account.id} ({account.name})")

        # 2. Fetch or create a mocked Strategy instance for the Breakout strategy
        #   Realistically this strategy would be selected by name or ID in the DB.
        #   For testing, we'll try to find one named 'EmaAtrBreakout', or just run the manual loop.
        strategy_result = await db.execute(
            select(Strategy)
            .where(Strategy.strategy_type == "Code")
            .where(Strategy.class_name == "EmaAtrBreakout")
            .limit(1)
        )
        db_strategy = strategy_result.scalar_one_or_none()

        strategy_instance = EmaAtrBreakout()
        
        symbols_to_trade = ["EURUSD", "GBPJPY", "XAGUSD", "XAUUSD", "AUDUSD"]
        timeframe = "H1"
        strategy_id = None

        if db_strategy:
            logger.info(f"Found Strategy ID: {db_strategy.id} in DB.")
            symbols_to_trade = db_strategy.symbols
            timeframe = db_strategy.timeframe
            strategy_id = db_strategy.id
            # Also apply any overrides like lot sizes if available on db_strategy 
            # (assuming standard properties or logic to map from db_strategy to execution)
        else:
            logger.warning(
                "EmaAtrBreakout not found in Strategy table. "
                "Falling back to default symbols and timeframe."
            )

        # 3. Initialize the AITradingService
        trading_service = AITradingService()

        # 4. Loop through symbols and execute strategy
        for symbol in symbols_to_trade:
            logger.info(f"--- Running logic for {symbol} on {timeframe} ---")
            try:
                result = await trading_service.analyze_and_trade(
                    account_id=account.id,
                    symbol=symbol,
                    timeframe=timeframe,
                    db=db,
                    strategy_id=strategy_id,
                    strategy_instance=strategy_instance,
                )
                logger.info(
                    f"Result for {symbol}: Action={result.signal.action}, "
                    f"Confidence={result.signal.confidence}, "
                    f"OrderPlaced={result.order_placed}"
                )
                if result.signal.action != "HOLD":
                    logger.info(f"Rationale: {result.signal.rationale}")
            except Exception as e:
                logger.error(f"Error executing strategy for {symbol}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
