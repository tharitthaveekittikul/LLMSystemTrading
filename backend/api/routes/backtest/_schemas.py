"""Pydantic response/request schemas shared by the backtest run routes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from db.models import BacktestRun, BacktestTrade

# ── Pydantic schemas ───────────────────────────────────────────────────────────

class BacktestRunRequest(BaseModel):
    strategy_id: int
    symbol: str = Field(..., min_length=1, max_length=20)
    timeframe: str | None = Field(default=None)  # None → use strategy's primary_tf
    start_date: datetime
    end_date: datetime
    initial_balance: float = Field(default=10_000.0, gt=0)
    spread_pips: float = Field(default=1.5, ge=0)
    execution_mode: str = Field(default="close_price")
    max_llm_calls: int = Field(default=100, ge=0)
    volume: float = Field(default=0.1, gt=0)
    risk_pct: float | None = Field(default=None, ge=0, le=1)  # e.g. 0.01 = 1%; None = fixed lot
    commission_per_lot: float = Field(default=0.0, ge=0)  # USD per lot (round trip)
    tp_partial_close_ratio: float = Field(default=0.5, gt=0, le=1)  # fraction to close at each TP
    skip_llm: bool = False                    # skip LLM calls; use rule-only fallback (rule_then_llm strategies)
    csv_upload_id: str | None = None          # primary TF CSV (backward compat)
    csv_uploads: dict[str, str] | None = None  # {tf_name: upload_id} for MTF CSVs


class BacktestRunSummary(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    spread_pips: float
    execution_mode: str
    status: str
    progress_pct: int
    error_message: str | None
    total_trades: int | None
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    max_drawdown_pct: float | None
    recovery_factor: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    total_return_pct: float | None
    avg_win: float | None
    avg_loss: float | None
    max_consec_wins: int | None
    max_consec_losses: int | None
    avg_spread: float | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, r: BacktestRun) -> "BacktestRunSummary":
        return cls(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            timeframe=r.timeframe,
            start_date=r.start_date.isoformat(),
            end_date=r.end_date.isoformat(),
            initial_balance=r.initial_balance,
            spread_pips=r.spread_pips,
            execution_mode=r.execution_mode,
            status=r.status,
            progress_pct=r.progress_pct,
            error_message=r.error_message,
            total_trades=r.total_trades,
            win_rate=r.win_rate,
            profit_factor=r.profit_factor,
            expectancy=r.expectancy,
            max_drawdown_pct=r.max_drawdown_pct,
            recovery_factor=r.recovery_factor,
            sharpe_ratio=r.sharpe_ratio,
            sortino_ratio=r.sortino_ratio,
            total_return_pct=r.total_return_pct,
            avg_win=r.avg_win,
            avg_loss=r.avg_loss,
            max_consec_wins=r.max_consec_wins,
            max_consec_losses=r.max_consec_losses,
            avg_spread=r.avg_spread,
            created_at=r.created_at.isoformat(),
        )


class BacktestTradeOut(BaseModel):
    id: int
    run_id: int
    symbol: str
    direction: str
    entry_time: str
    exit_time: str | None
    entry_price: float
    exit_price: float | None
    stop_loss: float
    take_profit: float
    volume: float
    profit: float | None
    exit_reason: str | None
    equity_after: float | None
    source: str | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, t: BacktestTrade) -> "BacktestTradeOut":
        return cls(
            id=t.id,
            run_id=t.run_id,
            symbol=t.symbol,
            direction=t.direction,
            entry_time=t.entry_time.isoformat(),
            exit_time=t.exit_time.isoformat() if t.exit_time else None,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            stop_loss=t.stop_loss,
            take_profit=t.take_profit,
            volume=t.volume,
            profit=t.profit,
            exit_reason=t.exit_reason,
            equity_after=t.equity_after,
            source=t.source,
        )

