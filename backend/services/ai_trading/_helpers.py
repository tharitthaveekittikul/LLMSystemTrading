"""Constants and pure/utility functions shared across the AI trading pipeline."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import LLMRoleResult
from core.llm_pricing import compute_cost

if TYPE_CHECKING:
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)

# ── MT5 TIMEFRAME integer constants (from MetaTrader5 Python library) ────────
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

# ── OHLCV cache TTL by timeframe (seconds) ──────────────────────────────────
_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}

# ── Minimum lot step for MT5 (universal across brokers) ─────────────────────
_MT5_MIN_LOT = 0.01


def _calculate_lot_size(
    balance: float,
    risk_pct: float,
    sl_pips: float,
    pip_value_per_lot: float,
    max_lot: float,
    min_lot: float = _MT5_MIN_LOT,
) -> float:
    """Compute risk-proportional lot size, clamped to [min_lot, max_lot].

    Args:
        balance: Current account balance in account currency.
        risk_pct: Fraction of balance to risk (e.g. 0.01 = 1%).
        sl_pips: Stop-loss distance in pips.
        pip_value_per_lot: Value of 1 pip for a 1.0-lot position in account currency.
        max_lot: Maximum allowed lot size (safety cap from account config).
        min_lot: Minimum MT5 lot step (default 0.01).

    Returns:
        Calculated lot size rounded to nearest min_lot step, between [min_lot, max_lot].
    """
    if balance <= 0 or sl_pips <= 0 or pip_value_per_lot <= 0:
        return min_lot
    raw = (balance * risk_pct) / (sl_pips * pip_value_per_lot)
    raw = round(raw / min_lot) * min_lot  # round to lot step
    return max(min_lot, min(raw, max_lot))


def _provider_name(llm: object) -> str:
    """Derive a short provider name from a LangChain LLM class."""
    mod = type(llm).__module__
    if "openai" in mod:
        return "openai"
    if "google" in mod or "gemini" in mod:
        return "gemini"
    if "anthropic" in mod:
        return "anthropic"
    return "unknown"


async def _get_task_llm(task: str, db: AsyncSession):
    """Load task-specific LLM from DB assignments. Returns None to use env-var default."""
    from sqlalchemy import select as _select

    from ai.orchestrator import _build_llm
    from core.security import decrypt as _decrypt
    from db.models import LLMProviderConfig, TaskLLMAssignment

    assignment = (await db.execute(
        _select(TaskLLMAssignment).where(TaskLLMAssignment.task == task)
    )).scalar_one_or_none()

    if not assignment or not assignment.provider:
        return None

    provider_row = (await db.execute(
        _select(LLMProviderConfig).where(
            LLMProviderConfig.provider == assignment.provider,
            LLMProviderConfig.is_active.is_(True),
        )
    )).scalar_one_or_none()

    if not provider_row:
        return None

    api_key = _decrypt(provider_row.encrypted_api_key)
    return _build_llm(
        provider=assignment.provider,
        api_key=api_key,
        model=assignment.model_name or None,
    )


def _news_direction(action: str) -> str:
    """Map a TradingSignal action to a simple BUY/SELL/HOLD direction for news gate comparison."""
    a = action.upper()
    if a.startswith("BUY"):
        return "BUY"
    if a.startswith("SELL"):
        return "SELL"
    return "HOLD"


async def record_llm_role(
    tracer: "PipelineTracer",
    role_result: LLMRoleResult,
    step_name: str,
    role: str,
    input_summary: dict,
) -> None:
    """Record a single LLM role's token usage to pipeline_steps + llm_calls tables."""
    input_payload = input_summary
    if getattr(role_result, "prompt", None):
        input_payload = {
            "summary": input_summary,
            "prompt": role_result.prompt
        }

    step_id = await tracer.record(
        step_name,
        input_data=input_payload,
        output_data={
            "model":         role_result.model,
            "provider":      role_result.provider,
            "input_tokens":  role_result.input_tokens,
            "output_tokens": role_result.output_tokens,
            "total_tokens":  role_result.total_tokens,
            "content": (
                role_result.content
                if isinstance(role_result.content, dict)
                else str(role_result.content)[:500]
            ),
        },
        duration_ms=role_result.duration_ms,
    )
    cost = (
        compute_cost(
            role_result.model,
            role_result.input_tokens or 0,
            role_result.output_tokens or 0,
        )
        if role_result.input_tokens is not None
        else None
    )
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
