# backend/services/hmm_retrain.py
"""HMM weekly retraining job — called by APScheduler."""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.config import settings
from core.security import decrypt
from db.models import AccountStrategy
from db.postgres import AsyncSessionLocal
from mt5.bridge import AccountCredentials, MT5Bridge
from services.hmm_service import HMMService

logger = logging.getLogger(__name__)

_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}
_HMM_TF      = "D1"
_HMM_TF_INT  = _TIMEFRAME_MAP["D1"]
_HMM_CANDLES = 365


async def retrain_all_hmm_models() -> None:
    """Retrain HMM for every active account/symbol combo. Called by APScheduler."""
    logger.info("HMM weekly retrain starting...")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AccountStrategy)
            .where(AccountStrategy.is_active.is_(True))
            # Bug Fix #4: eager-load both relationships inside the session
            .options(
                selectinload(AccountStrategy.strategy),
                selectinload(AccountStrategy.account),
            )
        )
        bindings = result.scalars().all()

        # Bug Fix #3: read all account attrs while session is still open,
        # then pass as plain dicts — never access ORM objects outside this block
        pairs: set[tuple[int, str]] = set()
        account_creds: dict[int, dict] = {}
        for b in bindings:
            if not b.account.is_active:
                continue
            symbols = json.loads(b.strategy.symbols or "[]")
            for sym in symbols:
                pairs.add((b.account_id, sym))
            if b.account_id not in account_creds:
                account_creds[b.account_id] = {
                    "login":              b.account.login,
                    "password_encrypted": b.account.password_encrypted,
                    "server":             b.account.server,
                    "mt5_path":           b.account.mt5_path,
                }

    for account_id, symbol in pairs:
        if account_id in account_creds:
            await _retrain_symbol(account_id, symbol, account_creds[account_id])

    logger.info("HMM weekly retrain complete | %d symbol pairs", len(pairs))


async def _retrain_symbol(account_id: int, symbol: str, creds_data: dict) -> None:
    try:
        password = decrypt(creds_data["password_encrypted"])
        creds = AccountCredentials(
            login=creds_data["login"],
            password=password,
            server=creds_data["server"],
            path=creds_data["mt5_path"] or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            candles = await bridge.get_rates(symbol, _HMM_TF_INT, _HMM_CANDLES)

        if not candles or len(candles) < 50:
            logger.warning("Not enough candles to retrain HMM | symbol=%s", symbol)
            return

        svc = HMMService(symbol=symbol, timeframe=_HMM_TF)
        svc.train(candles)

        # Invalidate pipeline cache so next run picks up the fresh model
        cache_key = f"{symbol}_{_HMM_TF}"
        from services.ai_trading import AITradingService
        AITradingService._hmm_cache.pop(cache_key, None)

        await _record_registry(symbol, len(candles), svc._model_path)

        logger.info(
            "HMM retrained | account=%d symbol=%s candles=%d",
            account_id, symbol, len(candles),
        )
    except Exception as exc:
        logger.error(
            "HMM retrain failed | account=%d symbol=%s: %s", account_id, symbol, exc
        )


async def _record_registry(symbol: str, candle_count: int, model_path: str) -> None:
    """Upsert a registry row so admins can see last retrain time per symbol."""
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from db.models import HMMModelRegistry
        now = datetime.now(UTC)
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(HMMModelRegistry).values(
                symbol=symbol,
                timeframe=_HMM_TF,
                trained_at=now,
                candle_count=candle_count,
                n_states=4,
                model_path=model_path,
                is_active=True,
            ).on_conflict_do_update(
                constraint="uq_hmm_symbol_timeframe",
                set_={
                    "trained_at":   now,
                    "candle_count": candle_count,
                    "model_path":   model_path,
                    "is_active":    True,
                },
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.warning("HMM registry record failed | symbol=%s: %s", symbol, exc)
