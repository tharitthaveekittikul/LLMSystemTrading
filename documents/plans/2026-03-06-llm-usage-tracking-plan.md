# LLM Usage Tracking & Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track per-call token usage across 3 split LLM pipeline roles (market analysis, chart vision, execution decision) and expose a `/llm-usage` dashboard showing cost, token consumption, and model breakdown across all providers.

**Architecture:** New `llm_calls` table stores one row per LLM invocation linked to a pipeline step. The AI orchestrator is refactored from a single `analyze_market()` call into 3 sequential role methods, each capturing token usage from LangChain `response_metadata`. The frontend `/llm-usage` page queries 4 new API endpoints backed by `llm_calls` queries.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), Alembic (migrations), LangChain (LLM calls), Next.js 16/TypeScript/Recharts (frontend), shadcn/ui (component library)

---

## Reference: Key File Locations

- Orchestrator: `backend/ai/orchestrator.py`
- Pipeline tracer: `backend/services/pipeline_tracer.py`
- AI trading service: `backend/services/ai_trading.py`
- DB models: `backend/db/models.py`
- Alembic migrations: `backend/alembic/versions/`
- API routes: `backend/api/routes/`
- FastAPI entry: `backend/main.py`
- Frontend types: `frontend/src/types/trading.ts`
- Frontend API client: `frontend/src/lib/api.ts`
- Frontend sidebar: `frontend/src/components/app-sidebar.tsx`
- Pipeline step card: `frontend/src/components/logs/pipeline-step-card.tsx`

## Reference: Token extraction from LangChain AIMessage

After `ai_msg = await llm.ainvoke(messages)`:
- **OpenAI**: `ai_msg.response_metadata.get("token_usage", {})` → `{"prompt_tokens": x, "completion_tokens": y, "total_tokens": z}`
- **Anthropic**: `ai_msg.response_metadata.get("usage", {})` → `{"input_tokens": x, "output_tokens": y}`
- **Gemini**: `ai_msg.usage_metadata` → has `.prompt_token_count`, `.candidates_token_count`, `.total_token_count`

## Reference: Latest Alembic revision

Current head: `c6a244581f53` — use as `down_revision` in the new migration.

---

## Task 1: Alembic Migration — `llm_calls` table

**Files:**
- Create: `backend/alembic/versions/a1b2c3d4e5f6_add_llm_calls_table.py`

**Step 1: Create the migration file**

```python
"""add_llm_calls_table

Revision ID: a1b2c3d4e5f6
Revises: c6a244581f53
Create Date: 2026-03-06 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'c6a244581f53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pipeline_step_id", sa.Integer(),
                  sa.ForeignKey("pipeline_steps.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("account_id", sa.Integer(),
                  sa.ForeignKey("accounts.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 8), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_llm_calls_created_at", "llm_calls", ["created_at"])
    op.create_index("idx_llm_calls_provider",   "llm_calls", ["provider"])
    op.create_index("idx_llm_calls_model",       "llm_calls", ["model"])


def downgrade() -> None:
    op.drop_index("idx_llm_calls_model",       table_name="llm_calls")
    op.drop_index("idx_llm_calls_provider",     table_name="llm_calls")
    op.drop_index("idx_llm_calls_created_at",   table_name="llm_calls")
    op.drop_table("llm_calls")
```

**Step 2: Run the migration**

```bash
# From backend/
uv run alembic upgrade head
```

Expected: `Running upgrade c6a244581f53 -> a1b2c3d4e5f6, add_llm_calls_table`

**Step 3: Verify table exists**

```bash
uv run python -c "
from sqlalchemy import create_engine, inspect
from core.config import settings
e = create_engine(settings.database_url.replace('+asyncpg', ''))
print(inspect(e).get_columns('llm_calls'))
"
```

Expected: prints list with id, pipeline_step_id, provider, model, role, input_tokens, output_tokens, total_tokens, cost_usd, duration_ms, created_at

---

## Task 2: Pricing Config + SQLAlchemy Model

**Files:**
- Create: `backend/core/llm_pricing.py`
- Modify: `backend/db/models.py`

**Step 1: Create `backend/core/llm_pricing.py`**

```python
"""LLM pricing table — cost per 1M tokens, USD.

Last verified: 2026-03-06.
Update this file when provider pricing changes.
Source: provider pricing pages (no public API for pricing).
"""
from decimal import Decimal

# Prices are per 1,000,000 tokens in USD.
LLM_PRICING: dict[str, dict[str, float]] = {
    # Google Gemini — https://ai.google.dev/pricing
    "gemini-2.5-flash":          {"input": 0.075,  "output": 0.30},
    "gemini-2.5-flash-image":    {"input": 0.075,  "output": 0.30},
    "gemini-2.0-flash":          {"input": 0.10,   "output": 0.40},
    "gemini-1.5-pro":            {"input": 1.25,   "output": 5.00},
    "gemini-1.5-flash":          {"input": 0.075,  "output": 0.30},
    # Anthropic Claude — https://www.anthropic.com/pricing
    "claude-sonnet-4-6":         {"input": 3.00,   "output": 15.00},
    "claude-opus-4-6":           {"input": 15.00,  "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 0.80,   "output": 4.00},
    # OpenAI — https://openai.com/pricing
    "gpt-4o":                    {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":               {"input": 0.15,   "output": 0.60},
    "gpt-4-turbo":               {"input": 10.00,  "output": 30.00},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return estimated cost in USD. Returns None if model is unknown."""
    pricing = LLM_PRICING.get(model)
    if pricing is None:
        return None
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 8)


def get_pricing_list() -> list[dict]:
    """Return list of {model, provider, input_per_1m, output_per_1m} for API responses."""
    provider_map = {
        "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-image", "gemini-2.0-flash",
                   "gemini-1.5-pro", "gemini-1.5-flash"],
        "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    }
    result = []
    for provider, models in provider_map.items():
        for model in models:
            p = LLM_PRICING.get(model, {})
            result.append({
                "model": model,
                "provider": provider,
                "input_per_1m_usd": p.get("input"),
                "output_per_1m_usd": p.get("output"),
            })
    return result
```

**Step 2: Add `LLMCall` SQLAlchemy model to `backend/db/models.py`**

After the `PipelineStep` class (around line 200), add:

```python
class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_step_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pipeline_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
```

**Step 3: Verify import works**

```bash
# From backend/
uv run python -c "from db.models import LLMCall; print('OK')"
uv run python -c "from core.llm_pricing import compute_cost; print(compute_cost('gemini-2.5-flash', 1000, 200))"
```

Expected:
- `OK`
- `0.000135` (1000 * 0.075 + 200 * 0.30) / 1e6 = 0.000135

---

## Task 3: Orchestrator Refactor — 3 LLM Role Methods

**Files:**
- Modify: `backend/ai/orchestrator.py`

This is the largest change. Replace the single `analyze_market()` with 3 role methods plus a coordinator.

**Step 1: Replace the entire `orchestrator.py` content**

The key changes are:
1. New `LLMRoleResult` dataclass for per-call token data
2. New `LLMAnalysisResult` with 3 role fields instead of `prompt_text`/`raw_response`
3. Helper `_call_llm_with_usage()` that invokes LLM directly (not via chain) to capture metadata
4. Three role methods: `_market_analysis()`, `_chart_vision()`, `_execution_decision()`
5. Updated `analyze_market()` calling all 3

```python
"""LangChain Orchestrator — all LLM interactions go through here.

Never call OpenAI / Gemini / Anthropic APIs directly from routes or services.
The signal pipeline: market data → market_analysis_llm → chart_vision_llm → execution_decision_llm → TradingSignal.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, field_validator

from core.config import settings

logger = logging.getLogger(__name__)


# ── Signal schema ─────────────────────────────────────────────────────────────

class TradingSignal(BaseModel):
    action: str = Field(..., description="BUY | SELL | HOLD")
    entry: float = Field(..., description="Recommended entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    take_profit: float = Field(..., description="Take profit price")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Signal confidence 0-1")
    rationale: str = Field(..., description="Brief explanation of the signal")
    timeframe: str = Field(..., description="Analysis timeframe e.g. M15")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in {"BUY", "SELL", "HOLD"}:
            raise ValueError("action must be BUY, SELL, or HOLD")
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


@dataclass
class LLMAnalysisResult:
    """Combined result from all 3 LLM role calls."""
    signal: TradingSignal
    market_analysis: LLMRoleResult
    chart_vision: LLMRoleResult | None    # None if no chart image provided
    execution_decision: LLMRoleResult


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_llm(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model from provider config or env-var settings."""
    resolved_provider = provider or settings.llm_provider

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key or settings.openai_api_key,
            temperature=0,
        )

    if resolved_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or settings.gemini_model,
            google_api_key=api_key or settings.gemini_api_key,
            temperature=0,
        )

    if resolved_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-sonnet-4-6",
            api_key=api_key or settings.anthropic_api_key,
            temperature=0,
        )

    raise ValueError(f"Unknown llm_provider: {resolved_provider!r}")


def _provider_from_llm(llm: BaseChatModel) -> str:
    """Derive short provider name from LangChain model class."""
    mod = type(llm).__module__
    if "openai" in mod:
        return "openai"
    if "google" in mod or "gemini" in mod:
        return "gemini"
    if "anthropic" in mod:
        return "anthropic"
    return "unknown"


def _model_name_from_llm(llm: BaseChatModel) -> str:
    """Extract model name string from LangChain model instance."""
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"


def _extract_tokens(ai_msg: Any, provider: str) -> tuple[int | None, int | None, int | None]:
    """Extract (input_tokens, output_tokens, total_tokens) from LangChain AIMessage."""
    try:
        if provider == "openai":
            usage = ai_msg.response_metadata.get("token_usage", {})
            inp = usage.get("prompt_tokens")
            out = usage.get("completion_tokens")
            total = usage.get("total_tokens")
            return inp, out, total

        if provider == "anthropic":
            usage = ai_msg.response_metadata.get("usage", {})
            inp = usage.get("input_tokens")
            out = usage.get("output_tokens")
            total = (inp or 0) + (out or 0) if inp is not None and out is not None else None
            return inp, out, total

        if provider == "gemini":
            meta = getattr(ai_msg, "usage_metadata", None)
            if meta is None:
                return None, None, None
            inp = getattr(meta, "prompt_token_count", None)
            out = getattr(meta, "candidates_token_count", None)
            total = getattr(meta, "total_token_count", None)
            return inp, out, total

    except Exception as exc:
        logger.debug("Could not extract token usage: %s", exc)
    return None, None, None


# ── Per-role LLM caller ────────────────────────────────────────────────────────

async def _call_llm_for_role(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    role: str,
) -> LLMRoleResult:
    """Invoke an LLM directly (not via chain) and return result with token usage."""
    provider = _provider_from_llm(llm)
    model = _model_name_from_llm(llm)
    t0 = time.monotonic()

    ai_msg = await llm.ainvoke(messages)
    duration_ms = int((time.monotonic() - t0) * 1000)

    raw_text = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
    inp, out, total = _extract_tokens(ai_msg, provider)

    # Parse JSON from the text response
    try:
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        content = json.loads(text)
    except Exception:
        content = raw_text

    logger.info(
        "LLM role=%s provider=%s model=%s input=%s output=%s total=%s duration=%dms",
        role, provider, model, inp, out, total, duration_ms,
    )
    return LLMRoleResult(
        content=content,
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        model=model,
        provider=provider,
        duration_ms=duration_ms,
        raw_text=raw_text,
    )


# ── Normaliser (shared) ────────────────────────────────────────────────────────

def _normalize_raw(raw: dict, *, timeframe: str, current_price: float) -> dict:
    """Map alternative LLM field names to the canonical TradingSignal schema."""
    out = dict(raw)

    if "action" not in out:
        for alias in ("signal", "side", "direction", "trade_action"):
            if alias in out:
                out["action"] = out.pop(alias)
                break

    if "rationale" not in out:
        for alias in ("explanation", "reason", "reasoning", "summary", "note"):
            if alias in out:
                out["rationale"] = out.pop(alias)
                break

    if "timeframe" not in out:
        out["timeframe"] = timeframe

    out.setdefault("action", "HOLD")
    out.setdefault("entry", current_price)
    out.setdefault("stop_loss", 0.0)
    out.setdefault("take_profit", 0.0)
    out.setdefault("confidence", 0.0)
    out.setdefault("rationale", "No rationale provided by model.")

    if isinstance(out.get("action"), str):
        out["action"] = out["action"].upper()

    logger.debug("LLM raw → normalised: %s", out)
    return out


# ── System prompts ─────────────────────────────────────────────────────────────

_MARKET_ANALYSIS_SYSTEM = """You are a professional forex market analyst.
Analyze the market data and return ONLY strictly valid JSON:
{{
  "trend": "bullish | bearish | ranging",
  "trend_strength": <float 0.0-1.0>,
  "key_support": <float>,
  "key_resistance": <float>,
  "volatility": "low | medium | high",
  "context_notes": "<2-3 sentence analysis of current market conditions>"
}}"""

_EXECUTION_SYSTEM = """You are a professional forex trader making execution decisions.
Based on the market analysis and position context provided, return ONLY strictly valid JSON.
Use EXACTLY these field names:
{{
  "action": "BUY | SELL | HOLD",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<brief 1-2 sentence explanation>",
  "timeframe": "<e.g. M15>"
}}

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or risk/reward is unfavorable.
- Check open positions before signaling. Avoid doubling same direction unless confidence > 0.90.
- Never open opposing positions simultaneously."""


# ── Role: Market Analysis ──────────────────────────────────────────────────────

async def _run_market_analysis(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict,
    ohlcv: list[dict],
    open_positions: list[dict],
    recent_signals: list[dict],
    news_context: str | None,
    trade_history_context: str | None,
    regime_context: str | None,
) -> LLMRoleResult:
    """LLM Role 1: Analyze market conditions and produce a context summary."""
    pos_lines = [
        f"  - {p.get('symbol', symbol)} {p.get('direction','?')} vol={p.get('volume','?')} profit={p.get('profit','?')}"
        for p in (open_positions or [])
    ] or ["  None"]
    sig_lines = [
        f"  - {s.get('symbol',symbol)} {s.get('signal','?')} conf={s.get('confidence','?')} | {s.get('rationale','')[:80]}"
        for s in (recent_signals or [])
    ]

    human_parts = [
        f"Symbol: {symbol}\nTimeframe: {timeframe}\nCurrent Price: {current_price}",
        f"\nIndicators:\n{json.dumps(indicators, indent=2)}",
    ]
    if regime_context:
        human_parts.append(f"\nMarket Regime (HMM):\n{regime_context}")
    human_parts.append(f"\nLast 20 OHLCV candles (oldest → newest):\n{json.dumps(ohlcv[-20:], indent=2, default=str)}")
    human_parts.append("\nCurrently Open Positions:\n" + "\n".join(pos_lines))
    if sig_lines:
        human_parts.append("\nRecent Signal History (newest first):\n" + "\n".join(sig_lines))
    if news_context:
        human_parts.append(f"\n{news_context}")
    if trade_history_context:
        human_parts.append(f"\n{trade_history_context}")
    human_parts.append("\nProvide the market context JSON.")

    messages = [
        SystemMessage(content=_MARKET_ANALYSIS_SYSTEM),
        HumanMessage(content="\n".join(human_parts)),
    ]
    return await _call_llm_for_role(llm, messages, "market_analysis")


# ── Role: Chart Vision ─────────────────────────────────────────────────────────

async def _run_chart_vision(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    chart_image_b64: str,
    market_context: dict,
) -> LLMRoleResult:
    """LLM Role 2: Analyze chart image and identify visual patterns."""
    system = """You are a technical chart analyst. Identify visual price patterns from the chart image.
Return ONLY strictly valid JSON:
{
  "chart_pattern": "<pattern name, e.g. double_top | head_shoulders | channel | none>",
  "pattern_direction": "bullish | bearish | neutral",
  "chart_notes": "<2-3 sentence description of what you see in the chart>"
}"""

    human_text = (
        f"Symbol: {symbol} | Timeframe: {timeframe}\n"
        f"Market Context: {json.dumps(market_context, indent=2)}\n"
        "Analyze this chart and return the visual pattern JSON."
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=[
            {"type": "text", "text": human_text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{chart_image_b64}"}},
        ]),
    ]
    return await _call_llm_for_role(llm, messages, "chart_vision")


# ── Role: Execution Decision ───────────────────────────────────────────────────

async def _run_execution_decision(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    current_price: float,
    market_context: dict,
    visual_pattern: dict | None,
    open_positions: list[dict],
    recent_signals: list[dict],
    system_prompt_override: str | None,
) -> LLMRoleResult:
    """LLM Role 3: Make final trade execution decision given all context."""
    system = system_prompt_override or _EXECUTION_SYSTEM

    pos_lines = [
        f"  - {p.get('symbol', symbol)} {p.get('direction','?')} vol={p.get('volume','?')} profit={p.get('profit','?')}"
        for p in (open_positions or [])
    ] or ["  None"]

    human_parts = [
        f"Symbol: {symbol}\nTimeframe: {timeframe}\nCurrent Price: {current_price}",
        f"\nMarket Analysis:\n{json.dumps(market_context, indent=2)}",
    ]
    if visual_pattern:
        human_parts.append(f"\nChart Pattern Analysis:\n{json.dumps(visual_pattern, indent=2)}")
    human_parts.append("\nCurrently Open Positions:\n" + "\n".join(pos_lines))
    if recent_signals:
        sig_lines = [
            f"  - {s.get('symbol',symbol)} {s.get('signal','?')} conf={s.get('confidence','?')} | {s.get('rationale','')[:80]}"
            for s in recent_signals
        ]
        human_parts.append("\nRecent Signal History:\n" + "\n".join(sig_lines))
    human_parts.append("\nProvide the trading signal JSON.")

    messages = [
        SystemMessage(content=system),
        HumanMessage(content="\n".join(human_parts)),
    ]
    return await _call_llm_for_role(llm, messages, "execution_decision")


# ── Public API ────────────────────────────────────────────────────────────────

async def analyze_market(
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict[str, Any],
    ohlcv: list[dict[str, Any]],
    chart_analysis: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    recent_signals: list[dict[str, Any]] | None = None,
    news_context: str | None = None,
    trade_history_context: str | None = None,
    regime_context: str | None = None,
    system_prompt_override: str | None = None,
    llm_override: BaseChatModel | None = None,
    # New: per-role LLM overrides
    market_analysis_llm: BaseChatModel | None = None,
    chart_vision_llm: BaseChatModel | None = None,
    execution_decision_llm: BaseChatModel | None = None,
) -> LLMAnalysisResult:
    """Run 3-role LLM analysis pipeline: market_analysis → chart_vision → execution_decision.

    Each role makes an independent LLM call and records token usage.
    llm_override applies to ALL roles if role-specific overrides are not set (legacy compat).
    """
    default_llm = llm_override or _build_llm()
    ma_llm  = market_analysis_llm    or default_llm
    cv_llm  = chart_vision_llm       or default_llm
    ed_llm  = execution_decision_llm or default_llm

    logger.info(
        "Analyzing market | symbol=%s timeframe=%s price=%s | providers: ma=%s cv=%s ed=%s",
        symbol, timeframe, current_price,
        _provider_from_llm(ma_llm), _provider_from_llm(cv_llm), _provider_from_llm(ed_llm),
    )

    # ── Role 1: Market Analysis ───────────────────────────────────────────────
    ma_result = await _run_market_analysis(
        ma_llm, symbol, timeframe, current_price,
        indicators, ohlcv, open_positions or [], recent_signals or [],
        news_context, trade_history_context, regime_context,
    )
    market_context = ma_result.content if isinstance(ma_result.content, dict) else {}

    # ── Role 2: Chart Vision (optional) ──────────────────────────────────────
    cv_result: LLMRoleResult | None = None
    visual_pattern: dict | None = None
    if chart_analysis:
        # chart_analysis is treated as base64 image if it starts with image markers,
        # otherwise as text analysis (for backward compatibility).
        if len(chart_analysis) > 200 and not chart_analysis.startswith("\n"):
            cv_result = await _run_chart_vision(
                cv_llm, symbol, timeframe, chart_analysis, market_context
            )
            visual_pattern = cv_result.content if isinstance(cv_result.content, dict) else None
        else:
            # Treat as pre-analyzed text — embed in market context
            market_context["chart_analysis_text"] = chart_analysis

    # ── Role 3: Execution Decision ────────────────────────────────────────────
    ed_result = await _run_execution_decision(
        ed_llm, symbol, timeframe, current_price,
        market_context, visual_pattern,
        open_positions or [], recent_signals or [],
        system_prompt_override,
    )

    raw = ed_result.content if isinstance(ed_result.content, dict) else {}
    raw = _normalize_raw(raw, timeframe=timeframe, current_price=current_price)
    signal = TradingSignal(**raw)

    # Confidence gate
    if signal.confidence < settings.llm_confidence_threshold:
        logger.info(
            "Signal downgraded to HOLD — confidence %.2f below threshold %.2f | symbol=%s",
            signal.confidence, settings.llm_confidence_threshold, symbol,
        )
        signal.action = "HOLD"

    logger.info(
        "Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
        symbol, signal.action, signal.confidence, signal.timeframe,
    )
    return LLMAnalysisResult(
        signal=signal,
        market_analysis=ma_result,
        chart_vision=cv_result,
        execution_decision=ed_result,
    )
```

**Step 2: Verify import works**

```bash
# From backend/
uv run python -c "from ai.orchestrator import analyze_market, LLMAnalysisResult, LLMRoleResult; print('OK')"
```

Expected: `OK`

---

## Task 4: PipelineTracer — `record_llm_call()` Helper

**Files:**
- Modify: `backend/services/pipeline_tracer.py`

Add a method that saves an `llm_calls` row and returns its ID, so `ai_trading.py` can link pipeline steps to LLM calls.

**Step 1: Add import and method to `PipelineTracer`**

At the top of the file, after existing imports, add:
```python
from db.models import LLMCall
```

After the `record()` method (before `finalize()`), add:

```python
    async def record_llm_call(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        cost_usd: float | None,
        duration_ms: int,
        pipeline_step_id: int | None = None,
    ) -> int | None:
        """Persist an llm_calls row. Returns the new row id."""
        if not self._db:
            return None
        call = LLMCall(
            pipeline_step_id=pipeline_step_id,
            account_id=self._account_id,
            provider=provider,
            model=model,
            role=role,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
        )
        self._db.add(call)
        await self._db.commit()
        await self._db.refresh(call)
        return call.id
```

Also update `record()` to return the new `PipelineStep.id` (needed to link llm_calls):

Change the `record()` signature return type from `None` to `int | None` and return `step.id`:

```python
    async def record(
        self,
        step_name: str,
        *,
        status: str = "ok",
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> int | None:
        """Persist a single pipeline step immediately. Returns the step id."""
        if not self._run or not self._db:
            return None
        self._seq += 1
        step = PipelineStep(
            run_id=self._run.id,
            seq=self._seq,
            step_name=step_name,
            status=status,
            input_json=json.dumps(input_data, default=str) if input_data is not None else None,
            output_json=json.dumps(output_data, default=str) if output_data is not None else None,
            error=error,
            duration_ms=duration_ms,
        )
        self._db.add(step)
        await self._db.commit()
        await self._db.refresh(step)
        return step.id
```

**Step 2: Verify import works**

```bash
uv run python -c "from services.pipeline_tracer import PipelineTracer; print('OK')"
```

Expected: `OK`

---

## Task 5: `ai_trading.py` — Wire 3 LLM Steps

**Files:**
- Modify: `backend/services/ai_trading.py`

**Step 1: Update imports at top of `ai_trading.py`**

Replace:
```python
from ai.orchestrator import LLMAnalysisResult, TradingSignal, analyze_market
```
With:
```python
from ai.orchestrator import LLMAnalysisResult, LLMRoleResult, TradingSignal, analyze_market
from core.llm_pricing import compute_cost
```

**Step 2: Update `_get_task_llm` calls — fetch 3 separate LLMs**

In `_run_pipeline`, replace the block starting at line 495 (`market_analysis_llm = await _get_task_llm("market_analysis", db)`) through the `tracer.record("llm_analyzed", ...)` call with:

```python
            # ── Fetch per-role LLM assignments from DB ───────────────────
            ma_llm  = await _get_task_llm("market_analysis", db)
            cv_llm  = await _get_task_llm("chart_vision", db)
            ed_llm  = await _get_task_llm("execution_decision", db)

            t0 = time.monotonic()
            llm_result: LLMAnalysisResult = await analyze_market(
                symbol=symbol,
                timeframe=tf_upper,
                current_price=current_price or 0,
                indicators=indicators,
                ohlcv=candles,
                open_positions=open_positions,
                recent_signals=recent_signals,
                news_context=news_context_str,
                trade_history_context=trade_history_context,
                regime_context=regime_context_str,
                system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
                market_analysis_llm=ma_llm,
                chart_vision_llm=cv_llm,
                execution_decision_llm=ed_llm,
            )
            signal = llm_result.signal

            # ── Record 3 LLM pipeline steps + llm_calls rows ─────────────
            async def _record_llm_role(
                role_result: LLMRoleResult,
                step_name: str,
                role: str,
                input_summary: dict,
            ) -> None:
                step_id = await tracer.record(
                    step_name,
                    input_data=input_summary,
                    output_data={
                        "model":   role_result.model,
                        "provider": role_result.provider,
                        "input_tokens":  role_result.input_tokens,
                        "output_tokens": role_result.output_tokens,
                        "total_tokens":  role_result.total_tokens,
                        "content": role_result.content if isinstance(role_result.content, dict)
                                   else str(role_result.content)[:500],
                    },
                    duration_ms=role_result.duration_ms,
                )
                cost = compute_cost(
                    role_result.model,
                    role_result.input_tokens or 0,
                    role_result.output_tokens or 0,
                ) if role_result.input_tokens is not None else None
                await tracer.record_llm_call(
                    role=role,
                    provider=role_result.provider,
                    model=role_result.model,
                    input_tokens=role_result.input_tokens,
                    output_tokens=role_result.output_tokens,
                    total_tokens=role_result.total_tokens,
                    cost_usd=cost,
                    duration_ms=role_result.duration_ms,
                    pipeline_step_id=step_id,
                )

            await _record_llm_role(
                llm_result.market_analysis,
                "market_analysis_llm",
                "market_analysis",
                {"symbol": symbol, "timeframe": tf_upper},
            )
            if llm_result.chart_vision is not None:
                await _record_llm_role(
                    llm_result.chart_vision,
                    "chart_vision_llm",
                    "chart_vision",
                    {"symbol": symbol, "has_image": True},
                )
            await _record_llm_role(
                llm_result.execution_decision,
                "execution_decision_llm",
                "execution_decision",
                {
                    "action":     signal.action,
                    "confidence": signal.confidence,
                },
            )
```

**Step 3: Update `journal.llm_provider` and `journal.model_name` (around line 567)**

Change:
```python
            llm_provider="rule_based" if rule_based else (
                _provider_name(market_analysis_llm) if market_analysis_llm else settings.llm_provider
            ),
            model_name=type(strategy_instance).__name__ if rule_based else "",
```
To:
```python
            llm_provider="rule_based" if rule_based else (
                llm_result.execution_decision.provider if not rule_based else settings.llm_provider
            ),
            model_name=type(strategy_instance).__name__ if rule_based else (
                llm_result.execution_decision.model if not rule_based else ""
            ),
```

**Step 4: Verify no import errors**

```bash
uv run python -c "from services.ai_trading import AITradingService; print('OK')"
```

Expected: `OK`

---

## Task 6: Backend API — LLM Usage Routes + Schemas

**Files:**
- Create: `backend/api/routes/llm_usage.py`

```python
"""LLM Usage API — token consumption and cost breakdown."""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm_pricing import get_pricing_list
from db.models import LLMCall
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Response schemas ──────────────────────────────────────────────────────────

class ProviderStats(BaseModel):
    cost_usd: float
    tokens: int
    calls: int


class LLMUsageSummary(BaseModel):
    total_cost_usd: float
    total_tokens: int
    total_calls: int
    active_models: list[str]
    by_provider: dict[str, ProviderStats]


class LLMTimeseriesPoint(BaseModel):
    date: str       # ISO date or "YYYY-MM-DD HH:00" for hourly
    google: float
    anthropic: float
    openai: float


class LLMModelUsage(BaseModel):
    model: str
    provider: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float


class LLMPricingEntry(BaseModel):
    model: str
    provider: str
    input_per_1m_usd: float | None
    output_per_1m_usd: float | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _period_start(period: str) -> datetime:
    now = datetime.now(UTC)
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    # month (default)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=LLMUsageSummary)
async def get_summary(
    period: str = Query("month", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
) -> LLMUsageSummary:
    since = _period_start(period)
    rows = (await db.execute(
        select(LLMCall).where(LLMCall.created_at >= since)
    )).scalars().all()

    total_cost = sum(float(r.cost_usd or 0) for r in rows)
    total_tokens = sum(r.total_tokens or 0 for r in rows)
    active_models = list({r.model for r in rows})

    by_provider: dict[str, ProviderStats] = {
        "google": ProviderStats(cost_usd=0, tokens=0, calls=0),
        "anthropic": ProviderStats(cost_usd=0, tokens=0, calls=0),
        "openai": ProviderStats(cost_usd=0, tokens=0, calls=0),
    }
    for r in rows:
        p = r.provider if r.provider in by_provider else "openai"
        by_provider[p].cost_usd += float(r.cost_usd or 0)
        by_provider[p].tokens += r.total_tokens or 0
        by_provider[p].calls += 1

    return LLMUsageSummary(
        total_cost_usd=round(total_cost, 8),
        total_tokens=total_tokens,
        total_calls=len(rows),
        active_models=active_models,
        by_provider=by_provider,
    )


@router.get("/timeseries", response_model=list[LLMTimeseriesPoint])
async def get_timeseries(
    granularity: str = Query("daily", pattern="^(daily|hourly)$"),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> list[LLMTimeseriesPoint]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (await db.execute(
        select(LLMCall).where(LLMCall.created_at >= since)
    )).scalars().all()

    # Bucket by date or hour
    buckets: dict[str, dict[str, float]] = {}
    for r in rows:
        if granularity == "hourly":
            key = r.created_at.strftime("%Y-%m-%d %H:00")
        else:
            key = r.created_at.strftime("%Y-%m-%d")
        if key not in buckets:
            buckets[key] = {"google": 0.0, "anthropic": 0.0, "openai": 0.0}
        provider = r.provider if r.provider in buckets[key] else "openai"
        buckets[key][provider] += float(r.cost_usd or 0)

    return [
        LLMTimeseriesPoint(
            date=k,
            google=round(v["google"], 8),
            anthropic=round(v["anthropic"], 8),
            openai=round(v["openai"], 8),
        )
        for k, v in sorted(buckets.items())
    ]


@router.get("/by-model", response_model=list[LLMModelUsage])
async def get_by_model(
    period: str = Query("month", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
) -> list[LLMModelUsage]:
    since = _period_start(period)
    rows = (await db.execute(
        select(LLMCall).where(LLMCall.created_at >= since)
    )).scalars().all()

    agg: dict[str, dict] = {}
    for r in rows:
        k = r.model
        if k not in agg:
            agg[k] = {
                "model": r.model, "provider": r.provider,
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
                "total_tokens": 0, "cost_usd": 0.0,
            }
        agg[k]["calls"] += 1
        agg[k]["input_tokens"]  += r.input_tokens  or 0
        agg[k]["output_tokens"] += r.output_tokens or 0
        agg[k]["total_tokens"]  += r.total_tokens  or 0
        agg[k]["cost_usd"]      += float(r.cost_usd or 0)

    return [LLMModelUsage(**v) for v in sorted(agg.values(), key=lambda x: -x["cost_usd"])]


@router.get("/pricing", response_model=list[LLMPricingEntry])
async def get_pricing() -> list[LLMPricingEntry]:
    return [LLMPricingEntry(**p) for p in get_pricing_list()]
```

---

## Task 7: Register Router in `main.py`

**Files:**
- Modify: `backend/main.py`

**Step 1: Add import**

After `from api.routes import storage as storage_routes`, add:
```python
from api.routes import llm_usage as llm_usage_routes
```

**Step 2: Add router registration**

After `app.include_router(storage_routes.router, ...)`, add:
```python
app.include_router(llm_usage_routes.router, prefix="/api/v1/llm-usage", tags=["llm-usage"])
```

**Step 3: Verify startup**

```bash
uv run uvicorn main:app --reload --port 8000
```

Expected: server starts, no import errors. Visit `http://localhost:8000/docs` (debug mode) — you should see the `llm-usage` section.

---

## Task 8: Frontend — Types + API Client

**Files:**
- Modify: `frontend/src/types/trading.ts`
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add LLM usage types to `trading.ts`**

Append at the end of the file:

```typescript
// ── LLM Usage ─────────────────────────────────────────────────────────────────

export interface LLMProviderStats {
  cost_usd: number
  tokens: number
  calls: number
}

export interface LLMUsageSummary {
  total_cost_usd: number
  total_tokens: number
  total_calls: number
  active_models: string[]
  by_provider: Record<string, LLMProviderStats>
}

export interface LLMTimeseriesPoint {
  date: string
  google: number
  anthropic: number
  openai: number
}

export interface LLMModelUsage {
  model: string
  provider: string
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
}

export interface LLMPricingEntry {
  model: string
  provider: string
  input_per_1m_usd: number | null
  output_per_1m_usd: number | null
}
```

**Step 2: Add `llmUsageApi` to `api.ts`**

Append at the end of the file:

```typescript
// ── LLM Usage ─────────────────────────────────────────────────────────────────

export const llmUsageApi = {
  getSummary: (period: "day" | "week" | "month" = "month") =>
    apiRequest<import("@/types/trading").LLMUsageSummary>(
      `/llm-usage/summary?period=${period}`
    ),

  getTimeseries: (params?: { granularity?: "daily" | "hourly"; days?: number }) => {
    const query = new URLSearchParams()
    if (params?.granularity) query.set("granularity", params.granularity)
    if (params?.days != null) query.set("days", String(params.days))
    const qs = query.toString()
    return apiRequest<import("@/types/trading").LLMTimeseriesPoint[]>(
      `/llm-usage/timeseries${qs ? `?${qs}` : ""}`
    )
  },

  getByModel: (period: "day" | "week" | "month" = "month") =>
    apiRequest<import("@/types/trading").LLMModelUsage[]>(
      `/llm-usage/by-model?period=${period}`
    ),

  getPricing: () =>
    apiRequest<import("@/types/trading").LLMPricingEntry[]>("/llm-usage/pricing"),
}
```

---

## Task 9: Frontend — LLM Usage Dashboard Components

**Files:**
- Create: `frontend/src/components/llm-usage/llm-usage-summary-cards.tsx`
- Create: `frontend/src/components/llm-usage/llm-usage-timeseries-chart.tsx`
- Create: `frontend/src/components/llm-usage/llm-usage-model-table.tsx`
- Create: `frontend/src/components/llm-usage/llm-provider-share-chart.tsx`
- Create: `frontend/src/components/llm-usage/llm-pricing-reference.tsx`

**Step 1: Create `llm-usage-summary-cards.tsx`**

```tsx
"use client"

import { DollarSign, Zap, Activity, Cpu } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMUsageSummary } from "@/types/trading"

const PROVIDER_COLORS: Record<string, string> = {
  google:    "text-blue-500",
  anthropic: "text-orange-500",
  openai:    "text-green-500",
}

function formatCost(usd: number): string {
  if (usd === 0) return "$0.00"
  if (usd < 0.001) return `$${usd.toFixed(6)}`
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

interface SummaryCardsProps {
  data: LLMUsageSummary
}

export function LLMUsageSummaryCards({ data }: SummaryCardsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Spend</CardTitle>
          <DollarSign className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatCost(data.total_cost_usd)}</p>
          <p className="text-xs text-muted-foreground mt-1">USD</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Tokens</CardTitle>
          <Zap className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatTokens(data.total_tokens)}</p>
          <p className="text-xs text-muted-foreground mt-1">across all calls</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Calls</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{data.total_calls}</p>
          <p className="text-xs text-muted-foreground mt-1">LLM invocations</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Active Models</CardTitle>
          <Cpu className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{data.active_models.length}</p>
          <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
            {data.active_models.slice(0, 2).map(m => (
              <p key={m} className="truncate">{m}</p>
            ))}
            {data.active_models.length > 2 && (
              <p>+{data.active_models.length - 2} more</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

**Step 2: Create `llm-usage-timeseries-chart.tsx`**

```tsx
"use client"

import { useState } from "react"
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import type { LLMTimeseriesPoint } from "@/types/trading"

const PROVIDER_COLORS = {
  google:    "#3b82f6",
  anthropic: "#f97316",
  openai:    "#22c55e",
}

interface TimeseriesChartProps {
  data: LLMTimeseriesPoint[]
  granularity: "daily" | "hourly"
  onGranularityChange: (g: "daily" | "hourly") => void
  metric: "spend" | "tokens"
  onMetricChange: (m: "spend" | "tokens") => void
}

function formatLabel(date: string, granularity: "daily" | "hourly") {
  if (granularity === "hourly") return date.slice(11, 16)
  return date.slice(5) // MM-DD
}

export function LLMUsageTimeseriesChart({
  data, granularity, onGranularityChange, metric, onMetricChange
}: TimeseriesChartProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Spend Over Time</CardTitle>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border text-xs">
              {(["spend", "tokens"] as const).map(m => (
                <button
                  key={m}
                  className={`px-2 py-1 capitalize transition-colors ${metric === m ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                  onClick={() => onMetricChange(m)}
                >
                  {m}
                </button>
              ))}
            </div>
            <div className="flex rounded-md border text-xs">
              {(["daily", "hourly"] as const).map(g => (
                <button
                  key={g}
                  className={`px-2 py-1 capitalize transition-colors ${granularity === g ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                  onClick={() => onGranularityChange(g)}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="date"
              tickFormatter={d => formatLabel(d, granularity)}
              tick={{ fontSize: 10 }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => metric === "spend" ? `$${v.toFixed(4)}` : v.toString()}
              width={60}
            />
            <Tooltip
              formatter={(v: number) => metric === "spend" ? [`$${v.toFixed(6)}`, ""] : [v, ""]}
            />
            <Legend />
            {(["google", "anthropic", "openai"] as const).map(p => (
              <Bar key={p} dataKey={p} stackId="a" fill={PROVIDER_COLORS[p]} name={p} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
```

**Step 3: Create `llm-usage-model-table.tsx`**

```tsx
"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { LLMModelUsage } from "@/types/trading"

const PROVIDER_BADGE: Record<string, string> = {
  google:    "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  anthropic: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  openai:    "bg-green-500/15 text-green-700 dark:text-green-400",
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

function fmtCost(usd: number) {
  if (usd === 0) return "—"
  if (usd < 0.001) return `$${usd.toFixed(6)}`
  return `$${usd.toFixed(4)}`
}

interface ModelTableProps {
  data: LLMModelUsage[]
}

export function LLMUsageModelTable({ data }: ModelTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Model Breakdown</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="text-left px-4 py-2 font-medium">Model</th>
                <th className="text-right px-4 py-2 font-medium">Calls</th>
                <th className="text-right px-4 py-2 font-medium">Input</th>
                <th className="text-right px-4 py-2 font-medium">Output</th>
                <th className="text-right px-4 py-2 font-medium">Total</th>
                <th className="text-right px-4 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.map(row => (
                <tr key={row.model} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={`text-xs ${PROVIDER_BADGE[row.provider] ?? ""}`}
                      >
                        {row.provider}
                      </Badge>
                      <span className="font-mono text-xs">{row.model}</span>
                    </div>
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums">{row.calls}</td>
                  <td className="text-right px-4 py-2.5 tabular-nums text-muted-foreground">
                    {fmtTokens(row.input_tokens)}
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums text-muted-foreground">
                    {fmtTokens(row.output_tokens)}
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums font-medium">
                    {fmtTokens(row.total_tokens)}
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums font-medium">
                    {fmtCost(row.cost_usd)}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    No LLM calls recorded yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
```

**Step 4: Create `llm-provider-share-chart.tsx`**

```tsx
"use client"

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMUsageSummary } from "@/types/trading"

const COLORS = { google: "#3b82f6", anthropic: "#f97316", openai: "#22c55e" }

interface ProviderShareProps {
  summary: LLMUsageSummary
}

export function LLMProviderShareChart({ summary }: ProviderShareProps) {
  const data = Object.entries(summary.by_provider)
    .map(([name, stats]) => ({ name, value: stats.cost_usd }))
    .filter(d => d.value > 0)

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Provider Share</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center h-32">
          <p className="text-sm text-muted-foreground">No data yet</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Provider Share (by cost)</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={70}
              innerRadius={40}
            >
              {data.map(entry => (
                <Cell
                  key={entry.name}
                  fill={COLORS[entry.name as keyof typeof COLORS] ?? "#888"}
                />
              ))}
            </Pie>
            <Tooltip
              formatter={(v: number) => [`$${v.toFixed(6)}`, "Cost"]}
            />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
```

**Step 5: Create `llm-pricing-reference.tsx`**

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { LLMPricingEntry } from "@/types/trading"

const PROVIDER_BADGE: Record<string, string> = {
  google:    "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  anthropic: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  openai:    "bg-green-500/15 text-green-700 dark:text-green-400",
}

interface PricingReferenceProps {
  data: LLMPricingEntry[]
}

export function LLMPricingReference({ data }: PricingReferenceProps) {
  // Only show models with pricing data
  const relevant = data.filter(d => d.input_per_1m_usd != null)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Model Pricing Reference</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y">
          {relevant.map(entry => (
            <div key={entry.model} className="flex items-center justify-between px-4 py-2.5">
              <div className="flex items-center gap-2">
                <Badge
                  variant="outline"
                  className={`text-xs ${PROVIDER_BADGE[entry.provider] ?? ""}`}
                >
                  {entry.provider}
                </Badge>
                <span className="font-mono text-xs">{entry.model}</span>
              </div>
              <div className="text-xs text-muted-foreground text-right">
                <span>In ${entry.input_per_1m_usd}/1M</span>
                <span className="mx-2">·</span>
                <span>Out ${entry.output_per_1m_usd}/1M</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
```

---

## Task 10: Frontend — LLM Usage Page

**Files:**
- Create: `frontend/src/app/llm-usage/page.tsx`

```tsx
"use client"

import { useCallback, useEffect, useState } from "react"
import { llmUsageApi } from "@/lib/api"
import type {
  LLMUsageSummary, LLMTimeseriesPoint, LLMModelUsage, LLMPricingEntry
} from "@/types/trading"
import { LLMUsageSummaryCards } from "@/components/llm-usage/llm-usage-summary-cards"
import { LLMUsageTimeseriesChart } from "@/components/llm-usage/llm-usage-timeseries-chart"
import { LLMUsageModelTable } from "@/components/llm-usage/llm-usage-model-table"
import { LLMProviderShareChart } from "@/components/llm-usage/llm-provider-share-chart"
import { LLMPricingReference } from "@/components/llm-usage/llm-pricing-reference"

type Period = "day" | "week" | "month"

export default function LLMUsagePage() {
  const [period, setPeriod] = useState<Period>("month")
  const [granularity, setGranularity] = useState<"daily" | "hourly">("daily")
  const [metric, setMetric] = useState<"spend" | "tokens">("spend")
  const [summary, setSummary] = useState<LLMUsageSummary | null>(null)
  const [timeseries, setTimeseries] = useState<LLMTimeseriesPoint[]>([])
  const [modelUsage, setModelUsage] = useState<LLMModelUsage[]>([])
  const [pricing, setPricing] = useState<LLMPricingEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const days = granularity === "hourly" ? 7 : 30
      const [s, ts, m, p] = await Promise.all([
        llmUsageApi.getSummary(period),
        llmUsageApi.getTimeseries({ granularity, days }),
        llmUsageApi.getByModel(period),
        llmUsageApi.getPricing(),
      ])
      setSummary(s)
      setTimeseries(ts)
      setModelUsage(m)
      setPricing(p)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load LLM usage data")
    } finally {
      setLoading(false)
    }
  }, [period, granularity])

  useEffect(() => { load() }, [load])

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">LLM Usage</h1>
          <p className="text-sm text-muted-foreground">Token consumption and API cost across all providers</p>
        </div>
        <div className="flex rounded-md border text-sm">
          {(["day", "week", "month"] as Period[]).map(p => (
            <button
              key={p}
              className={`px-3 py-1.5 capitalize transition-colors ${period === p ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setPeriod(p)}
            >
              {p === "day" ? "Today" : p === "week" ? "This Week" : "This Month"}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 text-destructive px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      {summary && <LLMUsageSummaryCards data={summary} />}

      {/* Timeseries Chart */}
      <LLMUsageTimeseriesChart
        data={timeseries}
        granularity={granularity}
        onGranularityChange={setGranularity}
        metric={metric}
        onMetricChange={setMetric}
      />

      {/* Model Table + Provider Share */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <LLMUsageModelTable data={modelUsage} />
        </div>
        <div>
          {summary && <LLMProviderShareChart summary={summary} />}
        </div>
      </div>

      {/* Pricing Reference */}
      <LLMPricingReference data={pricing} />
    </div>
  )
}
```

---

## Task 11: Sidebar + Pipeline Step Card Updates

**Files:**
- Modify: `frontend/src/components/app-sidebar.tsx`
- Modify: `frontend/src/components/logs/pipeline-step-card.tsx`

**Step 1: Add LLM Usage to sidebar**

In `app-sidebar.tsx`, add `Coins` to the lucide-react import and add to `navItems` array after Pipeline Logs:

```typescript
// Add to imports:
import { ..., Coins } from "lucide-react"

// Add to navItems after Pipeline Logs entry:
{ title: "LLM Usage", url: "/llm-usage", icon: Coins },
```

**Step 2: Update pipeline step card to show token badges**

In `pipeline-step-card.tsx`:

1. Add new step labels for the 3 new LLM steps to `STEP_LABELS`:
```typescript
  market_analysis_llm:    "Market Analysis (LLM)",
  chart_vision_llm:       "Chart Vision (LLM)",
  execution_decision_llm: "Execution Decision (LLM)",
  // Keep old one for backward compat with existing records:
  llm_analyzed:           "LLM Analysis (legacy)",
  hmm_regime:             "HMM Regime Detection",
  regime_gate:            "Regime Gate",
  rule_signal:            "Rule-Based Signal",
  lot_size_calculated:    "Lot Size Calculated",
```

2. Add a helper to detect LLM steps and extract token data from `output_json`:

```typescript
const LLM_STEP_NAMES = new Set([
  "market_analysis_llm",
  "chart_vision_llm",
  "execution_decision_llm",
  "llm_analyzed",
])

interface TokenInfo {
  model: string
  provider: string
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
}

function extractTokenInfo(step: PipelineStep): TokenInfo | null {
  if (!LLM_STEP_NAMES.has(step.step_name) || !step.output_json) return null
  try {
    const out = JSON.parse(step.output_json)
    if (!out.model && !out.input_tokens) return null
    return {
      model:         out.model        ?? "unknown",
      provider:      out.provider     ?? "unknown",
      input_tokens:  out.input_tokens  ?? null,
      output_tokens: out.output_tokens ?? null,
      total_tokens:  out.total_tokens  ?? null,
    }
  } catch {
    return null
  }
}
```

3. In the `PipelineStepCard` component, after the main row button, render token info if present:

```tsx
export function PipelineStepCard({ step }: PipelineStepCardProps) {
  const [expanded, setExpanded] = useState(false)
  const hasDetail = step.input_json || step.output_json || step.error
  const label = STEP_LABELS[step.step_name] ?? step.step_name
  const tokenInfo = extractTokenInfo(step)

  return (
    <div className="border-l-2 border-muted pl-4 py-1">
      <button
        className="flex items-center gap-2 w-full text-left group"
        onClick={() => hasDetail && setExpanded((v) => !v)}
        disabled={!hasDetail}
      >
        <span className="text-muted-foreground text-xs w-4 shrink-0">{step.seq}.</span>
        <span className="flex-1 text-sm font-medium">{label}</span>
        <Badge className={`text-xs shrink-0 ${STATUS_STYLES[step.status] ?? ""}`} variant="outline">
          {step.status}
        </Badge>
        <span className="text-xs text-muted-foreground w-16 text-right shrink-0">
          {step.duration_ms}ms
        </span>
        {hasDetail && (
          <span className="text-muted-foreground shrink-0">
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </span>
        )}
      </button>

      {/* Token info badge row for LLM steps */}
      {tokenInfo && (
        <div className="mt-1 ml-6 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono bg-muted/60 px-1.5 py-0.5 rounded">
            {tokenInfo.provider}/{tokenInfo.model}
          </span>
          {tokenInfo.input_tokens != null && (
            <>
              <span>↑ {tokenInfo.input_tokens.toLocaleString()} in</span>
              <span>↓ {tokenInfo.output_tokens?.toLocaleString()} out</span>
              <span className="font-medium">∑ {tokenInfo.total_tokens?.toLocaleString()} total</span>
            </>
          )}
        </div>
      )}

      {expanded && hasDetail && (
        <div className="mt-2 space-y-2">
          {step.error && (
            <div>
              <p className="text-xs font-semibold text-red-600 mb-1">Error</p>
              <pre className="text-xs bg-red-50 dark:bg-red-950/20 rounded p-2 text-red-700 dark:text-red-400 whitespace-pre-wrap">
                {step.error}
              </pre>
            </div>
          )}
          {step.input_json && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Input</p>
              <JsonViewer raw={step.input_json} />
            </div>
          )}
          {step.output_json && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Output</p>
              <JsonViewer raw={step.output_json} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

---

## Task 12: Verify recharts is installed

**Step 1: Check if recharts is already a dependency**

```bash
# From frontend/
cat package.json | grep recharts
```

If not present, install it:
```bash
npm install recharts
```

**Step 2: Verify build compiles**

```bash
npm run build
```

Expected: no TypeScript or build errors. If there are errors, fix them before proceeding.

---

## Final Verification Checklist

1. `uv run alembic upgrade head` — migration applied cleanly
2. `uv run python -c "from db.models import LLMCall; print('OK')"` — model imports
3. `uv run python -c "from ai.orchestrator import LLMAnalysisResult, LLMRoleResult; print('OK')"` — orchestrator exports
4. `uv run uvicorn main:app --reload --port 8000` — server starts without errors
5. `GET /api/v1/llm-usage/pricing` — returns pricing list JSON
6. `GET /api/v1/llm-usage/summary` — returns summary JSON (may be zeros if no calls yet)
7. `npm run dev` — frontend starts, `/llm-usage` route loads
8. Sidebar shows "LLM Usage" with Coins icon
9. Pipeline logs page — after a new pipeline run, LLM steps show token badge rows
