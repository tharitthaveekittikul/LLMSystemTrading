import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import accounts, analytics, trades, ws
from api.routes import signals
from api.routes import status
from api.routes import kill_switch as kill_switch_routes
from api.routes import strategies
from api.routes import pipeline as pipeline_routes
from api.routes import settings as settings_routes
from api.routes import backtest as backtest_routes
from api.routes import storage as storage_routes
from api.routes import llm_usage as llm_usage_routes
from api.routes import scheduler as scheduler_routes
from core.config import settings
from core.logging import setup_logging
from db.postgres import init_db
from db.questdb import init_questdb
from db.redis import close_redis

setup_logging()  # configure logging before anything else
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting LLM Trading System v%s | debug=%s | llm_provider=%s",
        app.version,
        settings.debug,
        settings.llm_provider,
    )
    await init_db()
    await init_questdb()
    logger.info("Database tables ready")

    # ── Load persisted global settings from DB ────────────────────────────────
    from db.postgres import AsyncSessionLocal
    from db.models import GlobalSettings as GlobalSettingsModel, TelegramSettings as TelegramSettingsModel
    from sqlalchemy import select as sa_select
    from core.security import decrypt as _decrypt
    async with AsyncSessionLocal() as _db:
        _row = (await _db.execute(
            sa_select(GlobalSettingsModel).where(GlobalSettingsModel.id == 1)
        )).scalar_one_or_none()
        if _row:
            settings.maintenance_interval_minutes = _row.maintenance_interval_minutes
            settings.maintenance_task_enabled = _row.maintenance_task_enabled
            settings.llm_confidence_threshold = _row.llm_confidence_threshold
            settings.news_enabled = _row.news_enabled
            logger.info(
                "Global settings loaded from DB | maintenance_interval=%dmin enabled=%s",
                _row.maintenance_interval_minutes,
                _row.maintenance_task_enabled,
            )

        _tg = (await _db.execute(
            sa_select(TelegramSettingsModel).where(TelegramSettingsModel.id == 1)
        )).scalar_one_or_none()
        if _tg and _tg.is_enabled and _tg.bot_token_encrypted and _tg.chat_id:
            settings.telegram_bot_token = _decrypt(_tg.bot_token_encrypted)
            settings.telegram_chat_id = _tg.chat_id
            logger.info("Telegram settings loaded from DB | chat_id=%s", _tg.chat_id)

    from services.equity_poller import run_equity_poller
    poller_task = asyncio.create_task(run_equity_poller())
    logger.info("Equity poller task started")

    from services.scheduler import start_scheduler, stop_scheduler
    from db.postgres import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await start_scheduler(db)

    yield

    stop_scheduler()
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    await close_redis()
    logger.info("Shutting down LLM Trading System")


app = FastAPI(
    title="LLM Trading System",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router,      prefix="/api/v1/accounts",    tags=["accounts"])
app.include_router(trades.router,        prefix="/api/v1/trades",      tags=["trades"])
app.include_router(analytics.router,     prefix="/api/v1/analytics",   tags=["analytics"])
app.include_router(status.router,        prefix="/api/v1/status",      tags=["status"])
app.include_router(signals.router,           prefix="/api/v1/signals",     tags=["signals"])
app.include_router(kill_switch_routes.router, prefix="/api/v1/kill-switch", tags=["kill-switch"])
app.include_router(ws.router,            prefix="/ws",                 tags=["websocket"])
app.include_router(strategies.router,    prefix="/api/v1/strategies",  tags=["strategies"])
app.include_router(pipeline_routes.router, prefix="/api/v1/pipeline", tags=["pipeline"])
app.include_router(settings_routes.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(backtest_routes.router, prefix="/api/v1/backtest", tags=["backtest"])
app.include_router(storage_routes.router, prefix="/api/v1/storage", tags=["storage"])
app.include_router(llm_usage_routes.router, prefix="/api/v1/llm-usage", tags=["llm-usage"])
app.include_router(scheduler_routes.router, prefix="/api/v1/scheduler", tags=["scheduler"])


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}
