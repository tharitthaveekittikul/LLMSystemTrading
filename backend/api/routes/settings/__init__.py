"""Settings API — LLM provider keys, task assignments, global/risk/telegram config.

Composed from sub-routers; the combined `router` matches the mount point
main.py already expects at prefix /api/v1/settings.
"""
from fastapi import APIRouter

from api.routes.settings._global import router as _global_router
from api.routes.settings._llm_providers import router as _llm_providers_router
from api.routes.settings._risk import router as _risk_router
from api.routes.settings._telegram import router as _telegram_router

router = APIRouter()
router.include_router(_llm_providers_router)
router.include_router(_global_router)
router.include_router(_risk_router)
router.include_router(_telegram_router)

__all__ = ["router"]
