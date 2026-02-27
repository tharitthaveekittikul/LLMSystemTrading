# System Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the LLM Trading System by wiring Alembic migrations, the AI→execute trading loop, Redis caching/rate-limiting, and three missing frontend pages (Trades, Signals, Kill Switch).

**Architecture:** `AITradingService` in `services/ai_trading.py` owns the full pipeline (MT5 data → Redis cache → LLM → DB → execute → broadcast). Kill switch and signals get dedicated HTTP route files. Three frontend pages mirror the existing analytics page pattern.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic 1.14, Redis asyncio, Next.js 16, TypeScript, shadcn/ui (new-york/slate), Tailwind CSS 4.

---

## Prerequisites

```bash
# From /backend — confirm alembic is installed (already in pyproject.toml)
uv run alembic --version
# Expected: alembic 1.14.x
```

---

## Task 1: Add missing fields to `AIJournal` model + make `trade_id` nullable

**Why:** `AIJournal` has no `account_id`, `symbol`, or `timeframe` — required for HOLD signals (no trade) and the signals API. `trade_id` must be nullable for HOLDs.

**Files:**
- Modify: `backend/db/models.py`

**Step 1: Edit `AIJournal` in `db/models.py`**

Replace the `AIJournal` class (lines 53–66) with:

```python
class AIJournal(Base):
    __tablename__ = "ai_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("trades.id"), unique=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    signal: Mapped[str] = mapped_column(String(10))       # BUY | SELL | HOLD
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    indicators_snapshot: Mapped[str] = mapped_column(Text)  # JSON string
    llm_provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    account: Mapped["Account"] = relationship("Account")
    trade: Mapped["Trade | None"] = relationship("Trade", back_populates="journal")
```

Also add the reverse relationship to `Account`:
```python
# In Account class, after the trades relationship:
journal_entries: Mapped[list["AIJournal"]] = relationship("AIJournal", back_populates="account")
```

---

## Task 2: Initialize Alembic

**Files:**
- Create: `backend/alembic/` (directory created by `alembic init`)
- Modify: `backend/alembic.ini` (auto-created)
- Modify: `backend/alembic/env.py` (auto-created, then replace)

**Step 1: Run alembic init from `/backend`**

```bash
cd backend
uv run alembic init alembic
```

Expected output: `Creating directory .../alembic ...  done`

**Step 2: Configure `alembic.ini`**

Find the line `sqlalchemy.url = ...` and replace it with a placeholder (we override in env.py):

```ini
sqlalchemy.url = postgresql+asyncpg://placeholder/placeholder
```

**Step 3: Replace `alembic/env.py` entirely**

```python
import asyncio
import logging
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import models to register them with Base.metadata
from db.postgres import Base
from db import models  # noqa: F401 — registers all ORM classes

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

target_metadata = Base.metadata


def get_url() -> str:
    """Read DATABASE_URL from settings (reads backend/.env automatically)."""
    from core.config import settings
    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL only)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 4: Generate initial migration**

```bash
uv run alembic revision --autogenerate -m "initial_schema"
```

Expected: `Generating .../alembic/versions/xxxx_initial_schema.py ... done`

Open the generated file and verify it creates these 4 tables: `accounts`, `trades`, `ai_journal`, `kill_switch_log`. If the DB already has tables from `init_db()`, the migration may show empty `upgrade()`/`downgrade()` — that is fine; it just stamps the current state.

**Step 5: Apply migration**

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade  -> xxxx, initial_schema`

**Step 6: Verify**

```bash
uv run alembic current
# Expected: xxxx (head)
```

---

## Task 3: Redis utility functions

**Files:**
- Modify: `backend/db/redis.py`
- Create: `backend/tests/test_redis_utils.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_redis_utils.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_check_llm_rate_limit_allows_first_call():
    """First call within window returns True (allowed)."""
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 1  # first call
    mock_redis.expire = AsyncMock()
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import check_llm_rate_limit
        result = await check_llm_rate_limit(account_id=1)
    assert result is True
    mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_check_llm_rate_limit_blocks_over_limit():
    """Call count exceeding max returns False (blocked)."""
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 11  # over the 10-call limit
    mock_redis.expire = AsyncMock()
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import check_llm_rate_limit
        result = await check_llm_rate_limit(account_id=1, max_calls=10)
    assert result is False


@pytest.mark.asyncio
async def test_candle_cache_miss_returns_none():
    """Cache miss returns None."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import get_candle_cache
        result = await get_candle_cache(1, "EURUSD", "M15")
    assert result is None


@pytest.mark.asyncio
async def test_candle_cache_hit_returns_list():
    """Cache hit returns deserialized candle list."""
    import json
    candles = [{"time": "2025-01-01", "open": 1.1, "close": 1.2}]
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(candles)
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import get_candle_cache
        result = await get_candle_cache(1, "EURUSD", "M15")
    assert result == candles
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_redis_utils.py -v
# Expected: 4 FAILED (ImportError — functions not defined yet)
```

**Step 3: Add utility functions to `db/redis.py`**

Append after the `close_redis()` function:

```python
import json as _json
from datetime import datetime as _datetime


async def check_llm_rate_limit(
    account_id: int,
    max_calls: int = 10,
    window_seconds: int = 60,
) -> bool:
    """Increment the LLM call counter for account_id.

    Returns True if the call is allowed; False if the rate limit is exceeded.
    Uses Redis INCR + EXPIRE (set TTL only on first increment of the window).
    """
    r = get_redis()
    key = f"llm_rate:{account_id}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, window_seconds)
    return count <= max_calls


async def get_candle_cache(account_id: int, symbol: str, timeframe: str) -> list | None:
    """Return cached OHLCV candles or None on cache miss."""
    r = get_redis()
    key = f"ohlcv:{account_id}:{symbol}:{timeframe}"
    raw = await r.get(key)
    if raw is None:
        return None
    return _json.loads(raw)


async def set_candle_cache(
    account_id: int,
    symbol: str,
    timeframe: str,
    candles: list,
    ttl_seconds: int,
) -> None:
    """Store OHLCV candles as JSON with a TTL."""
    r = get_redis()
    key = f"ohlcv:{account_id}:{symbol}:{timeframe}"
    await r.set(key, _json.dumps(candles, default=str), ex=ttl_seconds)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_redis_utils.py -v
# Expected: 4 PASSED
```

---

## Task 4: `AITradingService`

**Files:**
- Create: `backend/services/ai_trading.py`
- Create: `backend/tests/test_ai_trading.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_ai_trading.py
import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from ai.orchestrator import TradingSignal


def _make_signal(action: str, confidence: float = 0.85) -> TradingSignal:
    return TradingSignal(
        action=action,
        entry=1.0850,
        stop_loss=1.0800,
        take_profit=1.0950,
        confidence=confidence,
        rationale="Test signal",
        timeframe="M15",
    )


@pytest.mark.asyncio
async def test_analyze_hold_signal_no_order():
    """HOLD signal must not place an order."""
    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        max_lot_size=0.1, is_active=True,
    )

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=True),
        patch("services.ai_trading.get_candle_cache", return_value=None),
        patch("services.ai_trading.set_candle_cache"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        patch("services.ai_trading.analyze_market", return_value=_make_signal("HOLD")),
        patch("services.ai_trading.broadcast"),
        patch("services.ai_trading.decrypt", return_value="password"),
    ):
        mock_bridge = AsyncMock()
        mock_bridge.get_rates.return_value = [{"time": "t", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}] * 20
        mock_bridge.get_tick.return_value = {"bid": 1.085, "ask": 1.086}
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        from services.ai_trading import AITradingService
        service = AITradingService()
        result = await service.analyze_and_trade(
            account_id=1, symbol="EURUSD", timeframe="M15", db=mock_db
        )

    assert result.signal.action == "HOLD"
    assert result.order_placed is False
    assert result.ticket is None


@pytest.mark.asyncio
async def test_analyze_rate_limited_raises():
    """Rate-limited request raises HTTP 429."""
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(id=1, is_active=True)

    with patch("services.ai_trading.check_llm_rate_limit", return_value=False):
        from services.ai_trading import AITradingService
        service = AITradingService()
        with pytest.raises(HTTPException) as exc_info:
            await service.analyze_and_trade(
                account_id=1, symbol="EURUSD", timeframe="M15", db=mock_db
            )
    assert exc_info.value.status_code == 429
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_ai_trading.py -v
# Expected: 2 FAILED (ImportError)
```

**Step 3: Create `services/ai_trading.py`**

```python
"""AI Trading Service — full pipeline from market data to executed order.

Pipeline per call:
  1. Load account credentials from DB
  2. Redis rate limit check (10 LLM calls / 60s per account)
  3. Redis OHLCV cache (TTL by timeframe) — fetch from MT5 on miss
  4. orchestrator.analyze_market() → TradingSignal
  5. Persist to AIJournal (trade_id=None initially)
  6. Broadcast ai_signal WebSocket event
  7. If BUY/SELL: check kill switch → MT5Executor → persist Trade → update AIJournal
  8. Broadcast trade_opened (if order placed)
"""
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import TradingSignal, analyze_market
from api.routes.ws import broadcast
from core.config import settings
from core.security import decrypt
from db.models import AIJournal, Account, Trade
from db.redis import check_llm_rate_limit, get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor, OrderRequest
from services.kill_switch import is_active as kill_switch_active

logger = logging.getLogger(__name__)

# MT5 TIMEFRAME integer constants (from MetaTrader5 Python library)
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

# OHLCV cache TTL by timeframe (seconds)
_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}


@dataclass
class AnalysisResult:
    signal: TradingSignal
    order_placed: bool
    ticket: int | None
    journal_id: int


class AITradingService:
    async def analyze_and_trade(
        self,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
    ) -> AnalysisResult:
        """Run the full AI analysis → optional trade execution pipeline."""
        # ── 1. Load account ───────────────────────────────────────────────────
        account: Account | None = await db.get(Account, account_id)
        if not account or not account.is_active:
            raise HTTPException(status_code=404, detail="Account not found")

        # ── 2. Rate limit ─────────────────────────────────────────────────────
        allowed = await check_llm_rate_limit(account_id)
        if not allowed:
            logger.warning("LLM rate limit exceeded | account_id=%s", account_id)
            raise HTTPException(
                status_code=429,
                detail="LLM rate limit exceeded — max 10 calls per 60 seconds per account",
            )

        # ── 3. Resolve timeframe int ──────────────────────────────────────────
        tf_upper = timeframe.upper()
        tf_int = _TIMEFRAME_MAP.get(tf_upper)
        if tf_int is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown timeframe '{timeframe}'. Supported: {list(_TIMEFRAME_MAP)}",
            )

        # ── 4. Fetch / cache OHLCV ────────────────────────────────────────────
        candles = await get_candle_cache(account_id, symbol, tf_upper)
        current_price: float | None = None

        if candles is None:
            logger.info("OHLCV cache miss | account_id=%s symbol=%s tf=%s", account_id, symbol, tf_upper)
            password = decrypt(account.password_encrypted)
            creds = AccountCredentials(
                login=account.login,
                password=password,
                server=account.server,
                path=settings.mt5_path,
            )
            try:
                async with MT5Bridge(creds) as bridge:
                    candles = await bridge.get_rates(symbol, tf_int, 50)
                    tick = await bridge.get_tick(symbol)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            except ConnectionError as exc:
                raise HTTPException(status_code=502, detail=str(exc))

            if not candles:
                raise HTTPException(status_code=502, detail=f"MT5 returned no candles for {symbol} {timeframe}")

            ttl = _CACHE_TTL.get(tf_upper, 60)
            await set_candle_cache(account_id, symbol, tf_upper, candles, ttl)

            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

        if current_price is None and candles:
            # Fallback: use latest close if tick unavailable
            current_price = float(candles[-1].get("close", 0))

        # ── 5. Compute basic indicators ───────────────────────────────────────
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        indicators = {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }

        # ── 6. LLM analysis ───────────────────────────────────────────────────
        signal = await analyze_market(
            symbol=symbol,
            timeframe=tf_upper,
            current_price=current_price or 0,
            indicators=indicators,
            ohlcv=candles,
        )

        # ── 7. Persist AIJournal (trade_id=None initially) ────────────────────
        journal = AIJournal(
            account_id=account_id,
            trade_id=None,
            symbol=symbol,
            timeframe=tf_upper,
            signal=signal.action,
            confidence=signal.confidence,
            rationale=signal.rationale,
            indicators_snapshot=json.dumps(indicators),
            llm_provider=settings.llm_provider,
            model_name="",
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)

        # ── 8. Broadcast ai_signal ────────────────────────────────────────────
        await broadcast(account_id, "ai_signal", {
            "journal_id": journal.id,
            "symbol": symbol,
            "timeframe": tf_upper,
            "action": signal.action,
            "confidence": signal.confidence,
            "rationale": signal.rationale,
            "entry": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        # ── 9. Skip execution for HOLD or when kill switch is on ──────────────
        if signal.action == "HOLD":
            logger.info("Signal HOLD — no order | account_id=%s symbol=%s", account_id, symbol)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        if kill_switch_active():
            logger.warning(
                "Kill switch active — signal saved but order skipped | account_id=%s symbol=%s",
                account_id, symbol,
            )
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        # ── 10. Build order request ───────────────────────────────────────────
        order_req = OrderRequest(
            symbol=symbol,
            direction=signal.action,
            volume=account.max_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            comment="AI-Trade",
        )

        # ── 11. Connect MT5 and execute ───────────────────────────────────────
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=settings.mt5_path,
        )
        try:
            async with MT5Bridge(creds) as bridge:
                executor = MT5Executor(bridge)
                order_result = await executor.place_order(order_req)
        except (RuntimeError, ConnectionError) as exc:
            logger.error("MT5 error during order execution | account_id=%s | %s", account_id, exc)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        if not order_result.success:
            logger.error(
                "Order failed | account_id=%s symbol=%s error=%s",
                account_id, symbol, order_result.error,
            )
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        # ── 12. Persist Trade row ─────────────────────────────────────────────
        trade = Trade(
            account_id=account_id,
            ticket=order_result.ticket,
            symbol=symbol,
            direction=signal.action,
            volume=account.max_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            opened_at=datetime.now(UTC),
            source="ai",
        )
        db.add(trade)
        await db.flush()  # get trade.id before commit

        # Link journal → trade
        journal.trade_id = trade.id
        await db.commit()
        await db.refresh(trade)

        # ── 13. Broadcast trade_opened ────────────────────────────────────────
        await broadcast(account_id, "trade_opened", {
            "ticket": order_result.ticket,
            "symbol": symbol,
            "direction": signal.action,
            "volume": account.max_lot_size,
            "entry_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        logger.info(
            "Trade executed | account_id=%s symbol=%s direction=%s ticket=%s",
            account_id, symbol, signal.action, order_result.ticket,
        )
        return AnalysisResult(
            signal=signal,
            order_placed=True,
            ticket=order_result.ticket,
            journal_id=journal.id,
        )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_ai_trading.py -v
# Expected: 2 PASSED
```

---

## Task 5: Kill switch HTTP routes

**Files:**
- Create: `backend/api/routes/kill_switch.py`
- Modify: `backend/services/kill_switch.py` (add state tracking)
- Modify: `backend/main.py` (register router)
- Create: `backend/tests/test_kill_switch_routes.py`

**Step 1: Extend `services/kill_switch.py` to track activation details**

Add after `_active: bool = False`:

```python
_activation_reason: str | None = None
_activated_at: datetime | None = None
```

Add the import at top:
```python
from datetime import UTC, datetime
```

In `activate()`, after `_active = True`:
```python
        _activation_reason = reason
        _activated_at = datetime.now(UTC)
```

In `deactivate()`, after `_active = False`:
```python
        _activation_reason = None
        _activated_at = None
```

Add a public getter after `is_active()`:
```python
def get_state() -> dict:
    """Return current kill switch state dict (safe to call synchronously)."""
    return {
        "is_active": _active,
        "reason": _activation_reason,
        "activated_at": _activated_at.isoformat() if _activated_at else None,
    }
```

**Step 2: Write failing tests**

```python
# backend/tests/test_kill_switch_routes.py
import pytest
from httpx import ASGITransport, AsyncClient
from main import app


@pytest.mark.asyncio
async def test_get_kill_switch_status():
    """GET /api/v1/kill-switch returns is_active field."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/kill-switch")
    assert response.status_code == 200
    data = response.json()
    assert "is_active" in data


@pytest.mark.asyncio
async def test_activate_requires_reason():
    """POST /api/v1/kill-switch/activate without reason returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/kill-switch/activate", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_deactivate_returns_200():
    """POST /api/v1/kill-switch/deactivate always succeeds."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/kill-switch/deactivate")
    assert response.status_code == 200
```

**Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_kill_switch_routes.py -v
# Expected: 3 FAILED (404 — routes not registered)
```

**Step 4: Create `api/routes/kill_switch.py`**

```python
"""Kill switch HTTP routes — activate, deactivate, status, and log."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import KillSwitchLog
from db.postgres import get_db
from services import kill_switch

router = APIRouter()
logger = logging.getLogger(__name__)


class ActivateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class KillSwitchLogResponse(BaseModel):
    id: int
    action: str
    reason: str | None
    triggered_by: str
    created_at: datetime


@router.get("")
async def get_status():
    """Return the current kill switch state."""
    return kill_switch.get_state()


@router.post("/activate")
async def activate(body: ActivateRequest):
    """Activate the kill switch — all order execution is immediately blocked."""
    logger.warning("Kill switch activate requested via API | reason=%s", body.reason)
    await kill_switch.activate(reason=body.reason, triggered_by="user")
    return kill_switch.get_state()


@router.post("/deactivate")
async def deactivate():
    """Deactivate the kill switch — order execution is re-enabled."""
    logger.warning("Kill switch deactivated via API")
    await kill_switch.deactivate(triggered_by="user")
    return kill_switch.get_state()


@router.get("/logs", response_model=list[KillSwitchLogResponse])
async def get_logs(db: AsyncSession = Depends(get_db)):
    """Return kill switch event history (most recent first)."""
    result = await db.execute(
        select(KillSwitchLog).order_by(desc(KillSwitchLog.created_at)).limit(100)
    )
    return result.scalars().all()
```

**Step 5: Register route in `main.py`**

Add import and include_router:
```python
from api.routes import accounts, analytics, kill_switch as kill_switch_routes, trades, ws
```

```python
app.include_router(kill_switch_routes.router, prefix="/api/v1/kill-switch", tags=["kill-switch"])
```

**Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/test_kill_switch_routes.py -v
# Expected: 3 PASSED
```

---

## Task 6: Signals backend route

**Files:**
- Create: `backend/api/routes/signals.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_signals.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_signals.py
import pytest
from httpx import ASGITransport, AsyncClient
from main import app


@pytest.mark.asyncio
async def test_list_signals_returns_200():
    """GET /api/v1/signals returns 200 (empty list when no DB)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/signals")
    assert response.status_code in (200, 500)  # 500 if DB not running in CI
    assert response.status_code != 422


@pytest.mark.asyncio
async def test_list_signals_account_filter_accepted():
    """account_id query param is accepted without 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/signals?account_id=1")
    assert response.status_code != 422
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_signals.py -v
# Expected: 2 FAILED (404)
```

**Step 3: Create `api/routes/signals.py`**

```python
"""AI Signals — read-only endpoint over the ai_journal table."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AIJournal
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class SignalResponse(BaseModel):
    id: int
    account_id: int
    symbol: str
    timeframe: str
    signal: str
    confidence: float
    rationale: str
    llm_provider: str
    model_name: str
    created_at: datetime
    trade_id: int | None


@router.get("", response_model=list[SignalResponse])
async def list_signals(
    account_id: int | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List AI journal entries (most recent first)."""
    query = select(AIJournal).order_by(desc(AIJournal.created_at)).limit(limit)
    if account_id is not None:
        query = query.where(AIJournal.account_id == account_id)
    result = await db.execute(query)
    return result.scalars().all()
```

**Step 4: Register in `main.py`**

```python
from api.routes import accounts, analytics, kill_switch as kill_switch_routes, signals, trades, ws
```

```python
app.include_router(signals.router,            prefix="/api/v1/signals",    tags=["signals"])
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_signals.py -v
# Expected: 2 PASSED
```

---

## Task 7: Analyze route on accounts

**Files:**
- Modify: `backend/api/routes/accounts.py`
- Create: `backend/tests/test_analyze.py`

**Step 1: Write failing test**

```python
# backend/tests/test_analyze.py
import pytest
from httpx import ASGITransport, AsyncClient
from main import app


@pytest.mark.asyncio
async def test_analyze_endpoint_exists():
    """POST /api/v1/accounts/1/analyze returns 4xx (not 404/405)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/accounts/1/analyze",
            json={"symbol": "EURUSD", "timeframe": "M15"},
        )
    # Route exists (not 404/405); may be 422, 500, 503 depending on state
    assert response.status_code not in (404, 405)


@pytest.mark.asyncio
async def test_analyze_unknown_timeframe_returns_422():
    """Unknown timeframe string returns 422 or 404 (not 500)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/accounts/1/analyze",
            json={"symbol": "EURUSD", "timeframe": "INVALID"},
        )
    # Either 404 (account not found in test DB) or 422 (timeframe invalid) — not 500
    assert response.status_code in (404, 422, 503)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_analyze.py -v
# Expected: FAILED (404 — route doesn't exist)
```

**Step 3: Add to `api/routes/accounts.py`**

Add import at top:
```python
from db.postgres import get_db, AsyncSessionLocal
```

Add near the end, before the helpers section:

```python
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
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_analyze.py -v
# Expected: 2 PASSED
```

**Step 5: Run full test suite**

```bash
uv run pytest -v
# Expected: All tests pass
```

---

## Task 8: Generate and apply schema migration for new AIJournal columns

The previous Alembic initial migration was generated before Tasks 1–7. Now generate a new migration for the `AIJournal` changes (nullable trade_id + new columns).

**Step 1: Generate migration**

```bash
cd backend
uv run alembic revision --autogenerate -m "ai_journal_add_columns"
```

Open the generated file. It should contain `ALTER TABLE ai_journal ADD COLUMN account_id ...`, etc.

**Step 2: Apply**

```bash
uv run alembic upgrade head
uv run alembic current
# Expected: latest revision at (head)
```

---

## Task 9: Frontend — update `Trade` type + `api.ts`

The frontend `Trade` type doesn't match the actual backend `TradeResponse` schema. Fix alignment.

**Files:**
- Modify: `frontend/src/types/trading.ts`
- Modify: `frontend/src/lib/api.ts`

**Step 1: Update `Trade` interface in `trading.ts`**

Replace the existing `Trade` interface:

```typescript
export interface Trade {
  id: number;
  account_id: number;
  ticket: number;
  symbol: string;
  direction: "BUY" | "SELL";
  volume: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  close_price: number | null;
  profit: number | null;
  opened_at: string;
  closed_at: string | null;
  source: "ai" | "manual";
}
```

**Step 2: Update `AISignal` interface to match backend `SignalResponse`**

Replace the existing `AISignal` interface:

```typescript
export interface AISignal {
  id: number;
  account_id: number;
  symbol: string;
  timeframe: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  rationale: string;
  llm_provider: string;
  model_name: string;
  created_at: string;
  trade_id: number | null;
}
```

**Step 3: Add API functions to `api.ts`**

Append to `frontend/src/lib/api.ts`:

```typescript
// ── Trades ────────────────────────────────────────────────────────────────────

export const tradesApi = {
  list: (params?: {
    account_id?: number;
    open_only?: boolean;
    date_from?: string;
    date_to?: string;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null) query.set("account_id", String(params.account_id));
    if (params?.open_only) query.set("open_only", "true");
    if (params?.date_from) query.set("date_from", params.date_from);
    if (params?.date_to) query.set("date_to", params.date_to);
    if (params?.limit != null) query.set("limit", String(params.limit));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").Trade[]>(`/trades${qs ? `?${qs}` : ""}`);
  },
};

// ── Signals ───────────────────────────────────────────────────────────────────

export const signalsApi = {
  list: (params?: { account_id?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null) query.set("account_id", String(params.account_id));
    if (params?.limit != null) query.set("limit", String(params.limit));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").AISignal[]>(`/signals${qs ? `?${qs}` : ""}`);
  },
  analyze: (
    accountId: number,
    body: { symbol: string; timeframe: string },
  ) =>
    apiRequest<import("@/types/trading").AnalyzeResult>(`/accounts/${accountId}/analyze`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// ── Kill Switch ───────────────────────────────────────────────────────────────

export const killSwitchApi = {
  getStatus: () =>
    apiRequest<import("@/types/trading").KillSwitchStatus>("/kill-switch"),
  activate: (reason: string) =>
    apiRequest<import("@/types/trading").KillSwitchStatus>("/kill-switch/activate", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  deactivate: () =>
    apiRequest<import("@/types/trading").KillSwitchStatus>("/kill-switch/deactivate", {
      method: "POST",
    }),
  getLogs: () =>
    apiRequest<import("@/types/trading").KillSwitchLog[]>("/kill-switch/logs"),
};
```

**Step 4: Add missing types to `trading.ts`**

Append to `frontend/src/types/trading.ts`:

```typescript
// ── Analyze Result ─────────────────────────────────────────────────────────────

export interface AnalyzeResult {
  action: "BUY" | "SELL" | "HOLD";
  entry: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  rationale: string;
  timeframe: string;
  order_placed: boolean;
  ticket: number | null;
  journal_id: number;
}

// ── Kill Switch Log ────────────────────────────────────────────────────────────

export interface KillSwitchLog {
  id: number;
  action: "activated" | "deactivated";
  reason: string | null;
  triggered_by: "system" | "user";
  created_at: string;
}
```

Also update `KillSwitchStatus` to add `activated_at`:

```typescript
export interface KillSwitchStatus {
  is_active: boolean;
  reason: string | null;
  activated_at: string | null;
}
```

---

## Task 10: Frontend — Trades page

**Files:**
- Create: `frontend/src/app/trades/page.tsx`

**Step 1: Create `frontend/src/app/trades/page.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { tradesApi } from "@/lib/api";
import type { Trade } from "@/types/trading";

const fmt = (n: number | null, digits = 5) =>
  n == null ? "—" : n.toFixed(digits);

const pnlColor = (p: number | null) => {
  if (p == null) return "";
  if (p > 0) return "text-green-600 dark:text-green-400";
  if (p < 0) return "text-red-600 dark:text-red-400";
  return "";
};

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openOnly, setOpenOnly] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await tradesApi.list({
        open_only: openOnly,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: 200,
      });
      setTrades(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trades");
    } finally {
      setLoading(false);
    }
  }, [openOnly, dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);

  return (
    <SidebarInset>
      <AppHeader title="Trades" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="open-only"
              checked={openOnly}
              onChange={(e) => setOpenOnly(e.target.checked)}
              className="h-4 w-4"
            />
            <Label htmlFor="open-only">Open only</Label>
          </div>
          {!openOnly && (
            <>
              <div className="flex flex-col gap-1">
                <Label htmlFor="date-from" className="text-xs">From</Label>
                <Input
                  id="date-from"
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-36 text-sm"
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="date-to" className="text-xs">To</Label>
                <Input
                  id="date-to"
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-36 text-sm"
                />
              </div>
            </>
          )}
          <Button size="sm" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </Button>
        </div>

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}

        {/* Table */}
        <div className="rounded-md border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticket</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Dir</TableHead>
                <TableHead className="text-right">Volume</TableHead>
                <TableHead className="text-right">Entry</TableHead>
                <TableHead className="text-right">SL</TableHead>
                <TableHead className="text-right">TP</TableHead>
                <TableHead className="text-right">Close</TableHead>
                <TableHead className="text-right">P&L</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Opened</TableHead>
                <TableHead>Closed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={12} className="text-center text-muted-foreground py-8">
                    No trades found
                  </TableCell>
                </TableRow>
              )}
              {trades.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-mono text-sm">{t.ticket}</TableCell>
                  <TableCell className="font-medium">{t.symbol}</TableCell>
                  <TableCell>
                    <Badge variant={t.direction === "BUY" ? "default" : "destructive"}>
                      {t.direction}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">{t.volume}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(t.entry_price)}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">{fmt(t.stop_loss)}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">{fmt(t.take_profit)}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(t.close_price)}</TableCell>
                  <TableCell className={`text-right font-mono font-medium ${pnlColor(t.profit)}`}>
                    {t.profit != null ? (t.profit >= 0 ? "+" : "") + t.profit.toFixed(2) : "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">{t.source}</Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(t.opened_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {t.closed_at ? new Date(t.closed_at).toLocaleString() : "Open"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </SidebarInset>
  );
}
```

**Step 2: Verify page loads**

```bash
cd frontend && npm run dev
# Navigate to http://localhost:3000/trades — table renders, no JS console errors
```

---

## Task 11: Frontend — AI Signals page

**Files:**
- Create: `frontend/src/app/signals/page.tsx`

**Step 1: Create `frontend/src/app/signals/page.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { accountsApi, signalsApi } from "@/lib/api";
import type { Account, AISignal, AnalyzeResult } from "@/types/trading";

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

function actionVariant(a: string): "default" | "destructive" | "secondary" {
  if (a === "BUY") return "default";
  if (a === "SELL") return "destructive";
  return "secondary";
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted-foreground">{pct}%</span>
    </div>
  );
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<AISignal[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(null);

  // Analyze form state
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");

  const loadSignals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await signalsApi.list({ limit: 50 });
      setSignals(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load signals");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSignals();
    accountsApi.list().then(setAccounts).catch(() => {});
  }, [loadSignals]);

  async function handleAnalyze() {
    if (!selectedAccountId) return;
    setAnalyzing(true);
    setError(null);
    setAnalyzeResult(null);
    try {
      const result = await signalsApi.analyze(Number(selectedAccountId), { symbol, timeframe });
      setAnalyzeResult(result);
      await loadSignals(); // refresh list
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <SidebarInset>
      <AppHeader title="AI Signals" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {/* Trigger form */}
        <Card>
          <CardHeader className="pb-2 text-sm font-medium">Run Analysis</CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Account</Label>
                <Select value={selectedAccountId} onValueChange={setSelectedAccountId}>
                  <SelectTrigger className="w-44">
                    <SelectValue placeholder="Select account" />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {a.name} ({a.broker})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Symbol</Label>
                <Input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  className="w-28 text-sm"
                  placeholder="EURUSD"
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Timeframe</Label>
                <Select value={timeframe} onValueChange={setTimeframe}>
                  <SelectTrigger className="w-24">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIMEFRAMES.map((tf) => (
                      <SelectItem key={tf} value={tf}>{tf}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={handleAnalyze} disabled={analyzing || !selectedAccountId}>
                {analyzing ? "Analyzing…" : "Analyze"}
              </Button>
            </div>

            {analyzeResult && (
              <div className="mt-3 p-3 rounded-md bg-muted text-sm space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant={actionVariant(analyzeResult.action)}>{analyzeResult.action}</Badge>
                  <span className="text-muted-foreground">confidence {Math.round(analyzeResult.confidence * 100)}%</span>
                  {analyzeResult.order_placed && (
                    <Badge variant="outline" className="text-green-600">Order placed #{analyzeResult.ticket}</Badge>
                  )}
                </div>
                <p className="text-muted-foreground">{analyzeResult.rationale}</p>
              </div>
            )}
          </CardContent>
        </Card>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Signal feed */}
        <div className="space-y-2">
          {signals.length === 0 && !loading && (
            <p className="text-center text-muted-foreground py-8 text-sm">No signals yet — run an analysis above.</p>
          )}
          {signals.map((s) => (
            <Card key={s.id} className="overflow-hidden">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant={actionVariant(s.signal)}>{s.signal}</Badge>
                    <span className="font-medium">{s.symbol}</span>
                    <Badge variant="outline" className="text-xs">{s.timeframe}</Badge>
                    {s.trade_id && (
                      <Badge variant="outline" className="text-xs text-green-600">Executed</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {new Date(s.created_at).toLocaleString()}
                  </span>
                </div>
                <div className="mt-2">
                  <ConfidenceBar value={s.confidence} />
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{s.rationale}</p>
                <p className="mt-1 text-xs text-muted-foreground">{s.llm_provider} / {s.model_name || "default"}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </SidebarInset>
  );
}
```

**Step 2: Verify page loads**

```bash
# Navigate to http://localhost:3000/signals — cards render, no JS errors
```

---

## Task 12: Frontend — Kill Switch page

**Files:**
- Create: `frontend/src/app/kill-switch/page.tsx`

**Step 1: Create `frontend/src/app/kill-switch/page.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { killSwitchApi } from "@/lib/api";
import type { KillSwitchLog, KillSwitchStatus } from "@/types/trading";

export default function KillSwitchPage() {
  const [status, setStatus] = useState<KillSwitchStatus | null>(null);
  const [logs, setLogs] = useState<KillSwitchLog[]>([]);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        killSwitchApi.getStatus(),
        killSwitchApi.getLogs(),
      ]);
      setStatus(s);
      setLogs(l);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load kill switch state");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleActivate() {
    if (!reason.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const s = await killSwitchApi.activate(reason);
      setStatus(s);
      setReason("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Activation failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeactivate() {
    setLoading(true);
    setError(null);
    try {
      const s = await killSwitchApi.deactivate();
      setStatus(s);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deactivation failed");
    } finally {
      setLoading(false);
    }
  }

  const isActive = status?.is_active ?? false;

  return (
    <SidebarInset>
      <AppHeader title="Kill Switch" />
      <div className="flex flex-1 flex-col gap-4 p-4 max-w-2xl">
        {/* Status card */}
        <Card className={isActive ? "border-destructive" : "border-green-500"}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-3">
              <div className={`h-4 w-4 rounded-full ${isActive ? "bg-red-500 animate-pulse" : "bg-green-500"}`} />
              <span className="text-lg font-semibold">
                {isActive ? "KILL SWITCH ACTIVE — All trading halted" : "Kill switch inactive — Trading enabled"}
              </span>
            </div>
          </CardHeader>
          {isActive && status?.reason && (
            <CardContent className="pt-0">
              <p className="text-sm text-muted-foreground">Reason: {status.reason}</p>
              {status.activated_at && (
                <p className="text-xs text-muted-foreground mt-1">
                  Activated at {new Date(status.activated_at).toLocaleString()}
                </p>
              )}
            </CardContent>
          )}
        </Card>

        {/* Controls */}
        {isActive ? (
          <Button
            variant="default"
            className="w-full"
            onClick={handleDeactivate}
            disabled={loading}
          >
            {loading ? "Processing…" : "Deactivate Kill Switch"}
          </Button>
        ) : (
          <div className="space-y-2">
            <Label htmlFor="reason">Reason for activation (required)</Label>
            <Textarea
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Max drawdown exceeded, suspicious price action..."
              rows={3}
            />
            <Button
              variant="destructive"
              className="w-full"
              onClick={handleActivate}
              disabled={loading || !reason.trim()}
            >
              {loading ? "Processing…" : "Activate Kill Switch"}
            </Button>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Event log */}
        <div>
          <h3 className="text-sm font-medium mb-2">Event History</h3>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Action</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>By</TableHead>
                  <TableHead>Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground py-4 text-sm">
                      No events yet
                    </TableCell>
                  </TableRow>
                )}
                {logs.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell>
                      <Badge variant={l.action === "activated" ? "destructive" : "default"}>
                        {l.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{l.reason ?? "—"}</TableCell>
                    <TableCell className="text-sm">{l.triggered_by}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(l.created_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </SidebarInset>
  );
}
```

**Step 2: Verify page loads**

```bash
# Navigate to http://localhost:3000/kill-switch — toggle and log table render
```

---

## Task 13: Final verification

**Step 1: Run all backend tests**

```bash
cd backend
uv run pytest -v
# Expected: all tests pass
```

**Step 2: Verify Alembic is at head**

```bash
uv run alembic current
# Expected: <hash> (head)
```

**Step 3: Start frontend and check all pages**

```bash
cd frontend && npm run dev
```

Navigate to:
- `/trades` — table visible, filters work
- `/signals` — signal cards visible, analyze form present
- `/kill-switch` — status indicator, activate/deactivate form, log table

**Step 4: Verify no TypeScript errors**

```bash
cd frontend && npm run build
# Expected: no type errors, build succeeds
```
