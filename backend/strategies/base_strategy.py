"""Strategy base class hierarchy — 5 execution modes.

Each mode owns its own orchestration logic.
Strategy authors subclass the appropriate base and implement the required abstract methods.

Execution modes:
  LLMOnlyStrategy         — LLM called on every primary-TF candle close
  RuleThenLLMStrategy     — Rule pre-filter; LLM called only if rule fires
  RuleOnlyStrategy        — No LLM; fully deterministic (zero API cost)
  HybridValidatorStrategy — Rule executes immediately; LLM validates after entry
  MultiAgentStrategy      — Rule + LLM run in parallel; consensus required
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from services.mtf_data import MTFMarketData
    from db.models import Strategy


@dataclass
class StrategyResult:
    action: Literal["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"]
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    confidence: float
    rationale: str
    timeframe: str
    take_profit_levels: list[float] | None = None
    pattern_name: str | None = None
    pattern_metadata: dict | None = None
    llm_result: object | None = None   # LLMAnalysisResult if LLM was used


_HOLD = StrategyResult(
    action="HOLD", entry=None, stop_loss=None, take_profit=None,
    confidence=0.0, rationale="No signal", timeframe="",
)


def direction_from_action(action: str) -> str:
    """Return underlying direction: BUY_LIMIT -> BUY, SELL_STOP -> SELL, HOLD -> HOLD."""
    if action.startswith("BUY"):
        return "BUY"
    if action.startswith("SELL"):
        return "SELL"
    return "HOLD"


def is_market_order(action: str) -> bool:
    """True only for immediate market execution actions."""
    return action in {"BUY", "SELL"}


async def analyze_market(**kwargs):  # type: ignore[return]
    """Module-level proxy so patch('strategies.base_strategy.analyze_market') works in tests.

    Lazily imports ai.orchestrator to avoid loading LLM config at import time.
    """
    from ai.orchestrator import analyze_market as _analyze_market
    return await _analyze_market(**kwargs)


class AbstractStrategy(ABC):
    """Common interface for all strategy execution modes."""

    primary_tf: str = "M15"
    context_tfs: tuple[str, ...] = ("H1", "M1")   # immutable — subclasses assign a new tuple
    candle_counts: dict[str, int] = {"H1": 20, "M15": 10, "M1": 5}
    symbols: tuple[str, ...] = ()                  # immutable — subclasses assign a new tuple
    execution_mode: str = ""

    def apply_db_config(self, strategy_db: "Strategy") -> None:
        """Hydrate strategy attributes from the database configuration."""
        import json
        if strategy_db.primary_tf:
            self.primary_tf = strategy_db.primary_tf

        if strategy_db.context_tfs and strategy_db.context_tfs != "[]":
            try:
                # Store as tuple to match the type hint
                self.context_tfs = tuple(json.loads(strategy_db.context_tfs))
            except json.JSONDecodeError:
                pass

        if strategy_db.symbols and strategy_db.symbols != "[]":
            try:
                # Store as tuple to match the type hint
                self.symbols = tuple(json.loads(strategy_db.symbols))
            except json.JSONDecodeError:
                pass

    @abstractmethod
    async def run(self, market_data: "MTFMarketData") -> StrategyResult:
        """Execute the strategy and return a signal."""
        ...

    @abstractmethod
    def analytics_schema(self) -> dict:
        """Describe how the frontend should render analytics for this strategy type."""
        ...

    # ── Legacy compatibility ── keep generate_signal so old BacktestEngine still works
    def generate_signal(self, market_data: dict) -> dict | None:
        """Legacy single-TF interface. Returns None by default — use run() instead."""
        return None


class LLMOnlyStrategy(AbstractStrategy):
    """Type 1: LLM called on every primary-TF candle close.

    Author implements: system_prompt(), optionally build_context().
    Most expensive: one LLM call per candle regardless of market conditions.
    """
    execution_mode = "llm_only"

    @abstractmethod
    def system_prompt(self) -> str: ...

    def build_context(self, market_data: "MTFMarketData") -> str:
        """Override to customise the context string sent to LLM. Default structures H1->M15->M1."""
        parts = [f"Symbol: {market_data.symbol} | Primary TF: {market_data.primary_tf}"]
        for tf_name in [self.primary_tf] + self.context_tfs:
            tf_data = market_data.timeframes.get(tf_name)
            if tf_data and tf_data.candles:
                last = tf_data.candles[-1]
                parts.append(
                    f"{tf_name} last candle — O:{last.open} H:{last.high} L:{last.low} C:{last.close}"
                )
        return "\n".join(parts)

    async def run(self, market_data: "MTFMarketData") -> StrategyResult:
        ctx = self.build_context(market_data)
        result = await analyze_market(
            symbol=market_data.symbol,
            context=ctx,
            system_prompt=self.system_prompt(),
        )
        return StrategyResult(
            action=result.signal.action,
            entry=result.signal.entry,
            stop_loss=result.signal.stop_loss,
            take_profit=result.signal.take_profit,
            confidence=result.signal.confidence,
            rationale=result.signal.rationale,
            timeframe=self.primary_tf,
            llm_result=result,
        )

    def analytics_schema(self) -> dict:
        return {"panel_type": "llm_confidence", "group_by": None}


class RuleThenLLMStrategy(AbstractStrategy):
    """Type 2: Rule pre-filter; LLM called only if trigger fires.

    Author implements: check_trigger() -> bool, system_prompt().
    Cost saving: LLM called only when rule fires.
    """
    execution_mode = "rule_then_llm"

    @abstractmethod
    def check_trigger(self, market_data: "MTFMarketData") -> bool: ...

    @abstractmethod
    def system_prompt(self) -> str: ...

    async def run(self, market_data: "MTFMarketData") -> StrategyResult:
        if not self.check_trigger(market_data):
            return _HOLD
        result = await analyze_market(
            symbol=market_data.symbol,
            context=str(market_data.indicators),
            system_prompt=self.system_prompt(),
        )
        return StrategyResult(
            action=result.signal.action,
            entry=result.signal.entry,
            stop_loss=result.signal.stop_loss,
            take_profit=result.signal.take_profit,
            confidence=result.signal.confidence,
            rationale=result.signal.rationale,
            timeframe=self.primary_tf,
            llm_result=result,
        )

    def analytics_schema(self) -> dict:
        return {"panel_type": "rule_trigger", "group_by": None}


class RuleOnlyStrategy(AbstractStrategy):
    """Type 3: No LLM — fully deterministic rule-based signal.

    Author implements: check_rule() -> StrategyResult | None.
    Zero LLM cost. Ideal for pattern strategies (harmonic, SMC, CRT, etc.).
    """
    execution_mode = "rule_only"

    @abstractmethod
    def check_rule(self, market_data: "MTFMarketData") -> StrategyResult | None: ...

    async def run(self, market_data: "MTFMarketData") -> StrategyResult:
        result = self.check_rule(market_data)
        return result if result is not None else _HOLD

    def analytics_schema(self) -> dict:
        return {"panel_type": "pattern_grid", "group_by": "pattern_name"}


class HybridValidatorStrategy(AbstractStrategy):
    """Type 4: Rule executes first; LLM validates after order placement.

    Author implements: check_rule() -> StrategyResult | None, build_validation_context().
    Rule provides entry with zero LLM latency; LLM monitors position after entry.
    """
    execution_mode = "hybrid_validator"

    @abstractmethod
    def check_rule(self, market_data: "MTFMarketData") -> StrategyResult | None: ...

    def build_validation_context(self, signal: StrategyResult,
                                  market_data: "MTFMarketData") -> str:
        return (f"Open trade: {signal.action} {market_data.symbol} @ {signal.entry} "
                f"SL={signal.stop_loss} TP={signal.take_profit}. "
                f"Current price: {market_data.current_price}. Should we hold or exit early?")

    async def run(self, market_data: "MTFMarketData") -> StrategyResult:
        signal = self.check_rule(market_data)
        if signal is None:
            return _HOLD
        return signal

    def analytics_schema(self) -> dict:
        return {"panel_type": "validator", "group_by": None}


class MultiAgentStrategy(AbstractStrategy):
    """Type 5: Rule + LLM both run; consensus required to execute.

    Author implements: check_rule() -> StrategyResult | None, system_prompt().
    Most conservative: both must agree on direction. Disagreement -> HOLD.
    """
    execution_mode = "multi_agent"

    @abstractmethod
    def check_rule(self, market_data: "MTFMarketData") -> StrategyResult | None: ...

    @abstractmethod
    def system_prompt(self) -> str: ...

    async def run(self, market_data: "MTFMarketData") -> StrategyResult:
        import asyncio

        rule_result, llm_result = await asyncio.gather(
            self._get_rule_result(market_data),
            analyze_market(
                symbol=market_data.symbol,
                context=str(market_data.indicators),
                system_prompt=self.system_prompt(),
            ),
        )
        if rule_result is None or rule_result.action == "HOLD":
            return _HOLD
        if direction_from_action(llm_result.signal.action) != direction_from_action(rule_result.action):
            return _HOLD
        return StrategyResult(
            action=rule_result.action,
            entry=rule_result.entry,
            stop_loss=rule_result.stop_loss,
            take_profit=rule_result.take_profit,
            confidence=max(rule_result.confidence, llm_result.signal.confidence),
            rationale=f"Consensus: rule='{rule_result.rationale}' llm='{llm_result.signal.rationale}'",
            timeframe=self.primary_tf,
            llm_result=llm_result,
        )

    async def _get_rule_result(self, market_data: "MTFMarketData") -> StrategyResult | None:
        return self.check_rule(market_data)

    def analytics_schema(self) -> dict:
        return {"panel_type": "consensus", "group_by": None}


# ── Legacy alias — old code that imports BaseStrategy still works ───────────────
BaseStrategy = AbstractStrategy
