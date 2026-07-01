"""Strategies API — CRUD/registry, account bindings, per-strategy run analytics.

Composed from sub-routers; the combined `router` matches the mount point
main.py already expects at prefix /api/v1/strategies.
"""
from api.routes.strategies._analytics import router as _analytics_router
from api.routes.strategies._bindings import router as _bindings_router
from api.routes.strategies._crud import (
    BindingResponse,
    BindRequest,
    StrategyCreate,
    StrategyResponse,
    StrategyUpdate,
)
from api.routes.strategies._crud import (
    router as _crud_router,
)

# _crud_router is the base (not a fresh APIRouter) because it owns the ""
# (collection-root) routes — see accounts/__init__.py for why FastAPI's
# include_router() can't merge a router with an empty-string path into
# another empty-prefix router.
router = _crud_router
router.include_router(_bindings_router)
router.include_router(_analytics_router)

__all__ = [
    "BindRequest",
    "BindingResponse",
    "StrategyCreate",
    "StrategyResponse",
    "StrategyUpdate",
    "router",
]
