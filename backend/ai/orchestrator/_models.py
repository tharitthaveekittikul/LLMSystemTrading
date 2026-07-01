"""Data models shared across the orchestrator pipeline (signals, LLM role results)."""
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Signal schema ─────────────────────────────────────────────────────────────

_VALID_ACTIONS = frozenset({"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"})


class TradingSignal(BaseModel):
    action: str = Field(..., description="BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | HOLD")
    entry: float = Field(..., description="Recommended entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    take_profit: float = Field(..., description="Take profit price")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Signal confidence 0-1")
    rationale: str = Field(..., description="Brief explanation of the signal")
    timeframe: str = Field(..., description="Analysis timeframe e.g. M15")
    expiry_multiplier: float = Field(
        default=1.0,
        ge=0.5,
        le=3.0,
        description="Multiplier on default 4-candle pending order expiry. 1.0 = default.",
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in _VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(_VALID_ACTIONS)}")
        return v.upper()


@dataclass
class LLMRoleResult:
    """Result from a single LLM role call, including token usage."""
    content: Any                          # parsed dict or str output
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model: str
    provider: str
    duration_ms: int
    raw_text: str = ""                    # raw text response before parsing
    prompt: Any = None                    # Payload sent to the LLM


@dataclass
class LLMAnalysisResult:
    """Combined result from all LLM role calls."""
    signal: TradingSignal
    market_analysis: LLMRoleResult
    chart_vision: LLMRoleResult | None    # None if no chart image provided
    execution_decision: LLMRoleResult
    # Agent pipeline steps (None when using classic 3-role pipeline)
    indicator_agent: LLMRoleResult | None = None
    pattern_agent: LLMRoleResult | None = None
    trend_agent: LLMRoleResult | None = None
    # Trendline chart used by trend_agent (for UI display)
    trendline_chart_b64: str | None = None
    # Sub-agent vote breakdown + quorum verdict (Mode B only; None in the 3-role pipeline)
    vote_summary: dict | None = None


_VALID_MAINTENANCE_ACTIONS = frozenset({"HOLD", "CLOSE", "MODIFY"})


class MaintenanceDecision(BaseModel):
    """LLM output from the maintenance_decision role."""
    action: str = Field(..., description="HOLD | CLOSE | MODIFY")
    new_sl: float | None = Field(None, description="New stop loss price (MODIFY only)")
    new_tp: float | None = Field(None, description="New take profit price (MODIFY only)")
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., description="1-2 sentence explanation")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in _VALID_MAINTENANCE_ACTIONS:
            raise ValueError(f"action must be one of {sorted(_VALID_MAINTENANCE_ACTIONS)}")
        return v.upper()


@dataclass
class MaintenanceResult:
    """Combined result from the 3-role maintenance pipeline."""
    decision: MaintenanceDecision
    technical_analysis: LLMRoleResult
    sentiment_analysis: LLMRoleResult
    maintenance_decision: LLMRoleResult


@dataclass
class NewsAnalysisResult:
    """Result from the news analysis gate step."""
    signal: str          # "BUY" | "SELL" | "HOLD"
    reasoning: str
    role_result: LLMRoleResult | None = None  # None if LLM was skipped/errored

