"""Backtest API — submit runs, poll status, retrieve results.

Composed from sub-routers; the combined `router` matches the mount point
main.py already expects at prefix /api/v1/backtest.
"""
from fastapi import APIRouter

from api.routes.backtest._analytics import router as _analytics_router
from api.routes.backtest._optimize import router as _optimize_router
from api.routes.backtest._runs import router as _runs_router
from api.routes.backtest._schemas import BacktestRunRequest, BacktestRunSummary, BacktestTradeOut

router = APIRouter()
router.include_router(_runs_router)
router.include_router(_analytics_router)
router.include_router(_optimize_router)

__all__ = [
    "BacktestRunRequest",
    "BacktestRunSummary",
    "BacktestTradeOut",
    "router",
]
