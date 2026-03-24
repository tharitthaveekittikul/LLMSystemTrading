"""Strategy Registry — central catalogue of all available rule-based strategies.

Each entry declares:
  - display_name / description  (shown in UI)
  - module_path + class_name    (used by the engine to instantiate)
  - execution_mode              (auto-set from the class)
  - params                      (schema for dynamic config UI)

Adding a new strategy:
  1. Create the class in backend/strategies/<your_module>.py
  2. Add a StrategyMeta entry to REGISTRY below
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ParamField:
    """Describes one configurable parameter for the UI form."""
    name: str
    label: str
    type: Literal["int", "float", "bool", "str", "select"]
    default: Any
    description: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None   # only for type="select"
    optimize: bool = False             # whether this param can be swept in optimization

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "description": self.description,
            "optimize": self.optimize,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.step is not None:
            d["step"] = self.step
        if self.options is not None:
            d["options"] = self.options
        return d


@dataclass
class StrategyMeta:
    """Metadata for one registered strategy class."""
    key: str
    display_name: str
    description: str
    execution_mode: str
    module_path: str
    class_name: str
    params: list[ParamField] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "params": [p.to_dict() for p in self.params],
        }


# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, StrategyMeta] = {
    "crt": StrategyMeta(
        key="crt",
        display_name="Candle Range Theory (CRT)",
        description=(
            "Sweep-and-reclaim setups using a higher-timeframe reference candle (e.g., H4/D1). "
            "Detects liquidity sweeps beyond the reference range then enters on reclaim. "
            "Zero LLM cost."
        ),
        execution_mode="rule_only",
        module_path="strategies.crt.crt_strategy",
        class_name="CRTStrategy",
        params=[
            ParamField(
                name="target_rr",
                label="Target R:R",
                type="float",
                default=2.0,
                min=1.0,
                max=5.0,
                step=0.5,
                description="Risk:Reward ratio for take-profit calculation. TP = entry ± risk × R:R.",
                optimize=True,
            ),
            ParamField(
                name="sweep_buffer_pips",
                label="Sweep Buffer (pips)",
                type="float",
                default=0.0,
                min=0.0,
                max=10.0,
                step=0.5,
                description=(
                    "Extra price units beyond range boundary required to confirm a real sweep "
                    "(filters noise wicks). Raw price units — ~0.5 for XAUUSD, ~0.0003 for FX majors."
                ),
                optimize=True,
            ),
            ParamField(
                name="min_range_pips",
                label="Min Range (pips)",
                type="float",
                default=0.0,
                min=0.0,
                max=50.0,
                step=5.0,
                description="Minimum reference candle range size to consider the setup significant (0 = no filter).",
                optimize=True,
            ),
            ParamField(
                name="max_candles_after_sweep",
                label="Max Candles After Sweep",
                type="int",
                default=10,
                min=1,
                max=30,
                step=1,
                description="Maximum primary-TF candles after first sweep to still accept a reclaim entry. Prevents stale signals.",
                optimize=True,
            ),
        ],
    ),
    "harmonic": StrategyMeta(
        key="harmonic",
        display_name="Harmonic Patterns",
        description=(
            "Williams Fractals swing detection + 7 classic harmonic patterns "
            "(Gartley, Bat, Butterfly, Crab, Shark, Cypher, ABCD). "
            "Entry at PRZ with ATR-based SL/TP. Zero LLM cost."
        ),
        execution_mode="rule_only",
        module_path="strategies.harmonic.harmonic_strategy",
        class_name="HarmonicStrategy",
        params=[
            ParamField(
                name="fractal_n",
                label="Fractal N",
                type="int",
                default=2,
                min=1,
                max=10,
                step=1,
                description="Confirmation candles each side for Williams Fractals pivot detection.",
                optimize=True,
            ),
            ParamField(
                name="min_pattern_pips",
                label="Min Pattern Pips",
                type="float",
                default=0.0,
                min=0.0,
                max=50.0,
                step=5.0,
                description="Minimum XA leg size in pips (0 = no filter).",
                optimize=True,
            ),
            ParamField(
                name="prz_cooldown_candles",
                label="PRZ Cooldown (candles)",
                type="int",
                default=20,
                min=0,
                max=200,
                step=10,
                description="Suppress re-entry into the same PRZ for this many primary-TF candles.",
                optimize=True,
            ),
            ParamField(
                name="prz_tolerance_pct",
                label="PRZ Tolerance %",
                type="float",
                default=0.005,
                min=0.001,
                max=0.05,
                step=0.005,
                description="Price distance threshold to consider two entries in the same PRZ (0.5% default).",
                optimize=True,
            ),
        ],
    ),
    "orb": StrategyMeta(
        key="orb",
        display_name="Opening Range Breakout (ORB)",
        description=(
            "Session-based range breakout for XAUUSD H1. "
            "Accumulates the daily opening range after market open, waits for N candles "
            "to consolidate inside (range finalisation), then enters on a close-beyond-range "
            "breakout. Optional MA filter. Zero LLM cost. "
            "Translated from GOLD_ORB MQL5 EA."
        ),
        execution_mode="rule_only",
        module_path="strategies.orb.orb_strategy",
        class_name="ORBStrategy",
        params=[
            ParamField(
                name="start_hour",
                label="Session Start Hour (server)",
                type="int",
                default=1,
                min=0,
                max=6,
                step=1,
                description=(
                    "Server-time hour when the trading session opens. "
                    "For XAUUSD gold market typically opens at 01:00 server time."
                ),
                optimize=True,
            ),
            ParamField(
                name="candle_composition",
                label="Candle Composition",
                type="int",
                default=3,
                min=2,
                max=8,
                step=1,
                description=(
                    "Minimum consecutive H1 candles that must stay inside the range "
                    "without extending it before the range is considered final. "
                    "Higher = stricter range confirmation, fewer but higher-quality signals."
                ),
                optimize=True,
            ),
            ParamField(
                name="target_rr",
                label="Target R:R",
                type="float",
                default=3.0,
                min=1.5,
                max=5.0,
                step=0.5,
                description=(
                    "Risk:Reward ratio for take-profit. TP = entry ± risk × R:R. "
                    "Default 3.0 matches the original EA's TP=1200/SL=400 ratio."
                ),
                optimize=True,
            ),
            ParamField(
                name="use_ma_filter",
                label="Use MA Filter",
                type="bool",
                default=True,
                description=(
                    "Apply SMA filter: BUY only if close > SMA, SELL only if close < SMA. "
                    "Mirrors the MA100 filter in the original GOLD_ORB EA."
                ),
                optimize=False,
            ),
            ParamField(
                name="ma_period",
                label="MA Period",
                type="int",
                default=100,
                min=20,
                max=200,
                step=20,
                description="Period for the Simple Moving Average trend filter.",
                optimize=True,
            ),
            ParamField(
                name="min_range_pts",
                label="Min Range (pts)",
                type="float",
                default=0.0,
                min=0.0,
                max=200.0,
                step=20.0,
                description=(
                    "Minimum session range size in price units to accept the setup. "
                    "Filters sessions with very tight, low-significance ranges. "
                    "~20–50 for XAUUSD, 0 = no filter."
                ),
                optimize=True,
            ),
        ],
    ),
    "signal_score": StrategyMeta(
        key="signal_score",
        display_name="Signal Score (Nyao)",
        description=(
            "Weighted indicator scoring (EMA + RSI + ATR) ported from Nyao Scalper MQL5 EA. "
            "Rule pre-filter computes a 0–10 confidence score; LLM validates triggered signals. "
            "Designed for XAUUSD M15/H1. Use skip_llm=True for cost-free optimization sweeps."
        ),
        execution_mode="rule_then_llm",
        module_path="strategies.signal_score.signal_score_strategy",
        class_name="SignalScoreStrategy",
        params=[
            ParamField(
                name="ema_fast",
                label="EMA Fast Period",
                type="int",
                default=20,
                min=5,
                max=50,
                step=5,
                description="Fast EMA period for trend alignment. Lower = more responsive.",
                optimize=True,
            ),
            ParamField(
                name="ema_slow",
                label="EMA Slow Period",
                type="int",
                default=50,
                min=20,
                max=200,
                step=10,
                description="Slow EMA period for trend direction. Must be > ema_fast.",
                optimize=True,
            ),
            ParamField(
                name="rsi_period",
                label="RSI Period",
                type="int",
                default=14,
                min=7,
                max=21,
                step=7,
                description="RSI period for momentum scoring.",
                optimize=True,
            ),
            ParamField(
                name="atr_period",
                label="ATR Period",
                type="int",
                default=14,
                min=7,
                max=21,
                step=7,
                description="ATR period for volatility scoring and SL/TP calculation.",
                optimize=True,
            ),
            ParamField(
                name="min_score",
                label="Min Signal Score",
                type="float",
                default=5.5,
                min=4.0,
                max=8.0,
                step=0.5,
                description=(
                    "Minimum weighted score (0–10) to trigger a signal. "
                    "Higher = fewer but higher-conviction entries."
                ),
                optimize=True,
            ),
            ParamField(
                name="target_rr",
                label="Target R:R",
                type="float",
                default=2.0,
                min=1.5,
                max=5.0,
                step=0.5,
                description="Risk:Reward ratio for take-profit. TP = entry ± ATR × R:R.",
                optimize=True,
            ),
        ],
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_strategies() -> list[dict]:
    """Return all registered strategies as plain dicts (for the API)."""
    return [meta.to_dict() for meta in REGISTRY.values()]


def get_strategy(key: str) -> StrategyMeta | None:
    return REGISTRY.get(key)
