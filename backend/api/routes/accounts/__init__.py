"""Accounts API — CRUD, MT5 info, on-demand analysis, stats, sync, research loop.

Composed from sub-routers; the combined `router` matches the mount point
main.py already expects at prefix /api/v1/accounts.
"""
from api.routes.accounts._analyze import router as _analyze_router
from api.routes.accounts._crud import router as _crud_router
from api.routes.accounts._mt5_info import router as _mt5_info_router
from api.routes.accounts._research import router as _research_router
from api.routes.accounts._schemas import AccountCreate, AccountResponse, AccountUpdate
from api.routes.accounts._stats import router as _stats_router
from api.routes.accounts._sync import router as _sync_router

# _crud_router is the base (rather than a fresh empty APIRouter) because it
# owns the "" (collection-root) routes — FastAPI's include_router() refuses to
# merge a router that has an empty-string path into another empty-prefix
# router ("Prefix and path cannot be both empty"), so the router that holds
# the "" route has to be the one everything else attaches to, not the other
# way around.
router = _crud_router
router.include_router(_mt5_info_router)
router.include_router(_analyze_router)
router.include_router(_stats_router)
router.include_router(_sync_router)
router.include_router(_research_router)

__all__ = [
    "AccountCreate",
    "AccountResponse",
    "AccountUpdate",
    "router",
]
