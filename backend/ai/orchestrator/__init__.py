"""LangChain Orchestrator — all LLM interactions go through here.

Never call OpenAI / Gemini / Anthropic APIs directly from routes or services.
The signal pipeline: market data → market_analysis_llm → chart_vision_llm → execution_decision_llm → TradingSignal.

Public surface — matches the old ai/orchestrator.py module exactly.
"""
from ai.orchestrator._llm import _build_llm, _call_llm_for_role, log_llm_usage
from ai.orchestrator._models import (
    LLMAnalysisResult,
    LLMRoleResult,
    MaintenanceDecision,
    MaintenanceResult,
    NewsAnalysisResult,
    TradingSignal,
)
from ai.orchestrator._pipeline import (
    analyze_market,
    analyze_news_impact,
    review_position,
    run_agent_pipeline,
)

__all__ = [
    "LLMAnalysisResult",
    "LLMRoleResult",
    "MaintenanceDecision",
    "MaintenanceResult",
    "NewsAnalysisResult",
    "TradingSignal",
    "_build_llm",
    "_call_llm_for_role",
    "analyze_market",
    "analyze_news_impact",
    "log_llm_usage",
    "review_position",
    "run_agent_pipeline",
]
