"""LLM Analytics API — model performance tied to trade outcomes, plus research-loop learning views.

Composed from sub-routers; the combined `router` matches the mount point
main.py already expects at prefix /api/v1/llm-analytics.
"""
from fastapi import APIRouter

from api.routes.llm_analytics._learning import router as _learning_router
from api.routes.llm_analytics._performance import router as _performance_router

router = APIRouter()
router.include_router(_performance_router)
router.include_router(_learning_router)

__all__ = ["router"]
