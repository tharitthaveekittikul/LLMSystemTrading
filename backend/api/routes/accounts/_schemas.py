"""Pydantic request/response schemas for the accounts routes."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class AccountStatsResponse(BaseModel):
    win_rate: float
    total_pnl: float
    trade_count: int
    winning_trades: int


class SyncOrdersResponse(BaseModel):
    total_checked: int
    positions_closed: int   # open positions manually closed in MT5
    orders_cancelled: int   # pending orders cancelled/expired in MT5
    unchanged: int


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


class SyncAllResponse(BaseModel):
    imported: int
    updated: int = 0
    total_fetched: int
    accounts_synced: int
    errors: list[str]


class EquityPoint(BaseModel):
    ts: str
    equity: float
    balance: float


