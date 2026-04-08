"""Domain models for the AI trading pipeline."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from ai.orchestrator import LLMAnalysisResult, TradingSignal


class StrategyOverrides(BaseModel):
    """Per-strategy execution overrides passed from the scheduler."""
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    custom_prompt: str | None = None
    news_filter: bool = False


@dataclass
class SharedMarketContext:
    """Market analysis result shared across accounts in a group job."""
    symbol: str
    mt5_symbol: str
    timeframe: str
    candles: list[dict]
    indicators: dict
    current_price: float
    signal: TradingSignal
    llm_result: LLMAnalysisResult | None = None
    news_signal: str | None = None


@dataclass
class AnalysisResult:
    """Return value of AITradingService.analyze_and_trade."""
    signal: TradingSignal
    order_placed: bool
    ticket: int | None
    journal_id: int
    shared_ctx: SharedMarketContext | None = None
