"""AI Trading Service package.

Public surface — matches the old services/ai_trading.py module exactly.
"""
from services.ai_trading._helpers import _get_task_llm
from services.ai_trading._models import AnalysisResult, SharedMarketContext, StrategyOverrides
from services.ai_trading._service import AITradingService

__all__ = [
    "AITradingService",
    "AnalysisResult",
    "SharedMarketContext",
    "StrategyOverrides",
    "_get_task_llm",
]
