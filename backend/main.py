import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware import RequestLoggingMiddleware
from api.routes import accounts, analytics, signals, status, strategies, trades, ws
from api.routes import backtest as backtest_routes
from api.routes import kill_switch as kill_switch_routes
from api.routes import llm_analytics as llm_analytics_routes
from api.routes import llm_usage as llm_usage_routes
from api.routes import logs_ingest as logs_ingest_routes
from api.routes import logs_system as logs_system_routes
from api.routes import market_data as market_data_routes
from api.routes import news as news_routes
from api.routes import pipeline as pipeline_routes
from api.routes import scheduler as scheduler_routes
from api.routes import settings as settings_routes
from api.routes import storage as storage_routes
from api.routes import system as system_routes
from core.config import settings
from core.logging import attach_websocket_log_handler, fix_uvicorn_logging, setup_logging
from db.postgres import init_db
from db.questdb import init_questdb
from db.redis import close_redis

setup_logging()  # configure logging before anything else
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    fix_uvicorn_logging()  # strip uvicorn's own handlers; use our root formatter
    attach_websocket_log_handler(asyncio.get_running_loop())  # System Logs live tail
    logger.info(
        "Starting LLM Trading System v%s | debug=%s | llm_provider=%s",
        app.version,
        settings.debug,
        settings.llm_provider,
    )
    await init_db()
    await init_questdb()
    logger.info("Database tables ready")

    # ── Recover optimization runs interrupted by a backend restart ────────────
    # Runs stuck in "running"/"cancelling" will never finish; mark them cancelled
    # so the UI unblocks and the user can resume from partial results.
    from sqlalchemy import select as _sa_select

    from db.models import OptimizationRun
    from db.postgres import AsyncSessionLocal as _AsyncSessionLocal
    async with _AsyncSessionLocal() as _db:
        _stuck = (await _db.execute(
            _sa_select(OptimizationRun).where(
                OptimizationRun.status.in_(["running", "cancelling"])
            )
        )).scalars().all()
        for _o in _stuck:
            _o.status = "cancelled"
            _o.error_message = "Backend restarted while optimization was running"
        if _stuck:
            await _db.commit()
            logger.warning(
                "Reset %d stuck optimization run(s) to 'cancelled' on startup",
                len(_stuck),
            )

    # ── Load persisted global settings from DB ────────────────────────────────
    from sqlalchemy import select as sa_select

    from core.security import decrypt as _decrypt
    from db.models import TelegramSettings as TelegramSettingsModel
    from db.postgres import AsyncSessionLocal
    from services.settings_bootstrap import ensure_global_settings_row
    async with AsyncSessionLocal() as _db:
        # Creates the row (seeded from config defaults/.env) only if one has
        # never been persisted before — an existing row is never mutated, so
        # a prior explicit choice (including news_enabled=False) is preserved.
        _row = await ensure_global_settings_row(_db)
        settings.maintenance_interval_minutes = _row.maintenance_interval_minutes
        settings.maintenance_task_enabled = _row.maintenance_task_enabled
        settings.llm_confidence_threshold = _row.llm_confidence_threshold
        settings.news_enabled = _row.news_enabled
        settings.enable_agent_pipeline = _row.enable_agent_pipeline
        settings.enable_indicator_agent = _row.enable_indicator_agent
        settings.enable_pattern_agent = _row.enable_pattern_agent
        settings.enable_trend_agent = _row.enable_trend_agent
        logger.info(
            "Global settings loaded from DB | maintenance_interval=%dmin enabled=%s agent_pipeline=%s news_enabled=%s",
            _row.maintenance_interval_minutes,
            _row.maintenance_task_enabled,
            _row.enable_agent_pipeline,
            _row.news_enabled,
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

    from db.postgres import AsyncSessionLocal
    from services.scheduler import start_scheduler, stop_scheduler
    async with AsyncSessionLocal() as db:
        await start_scheduler(db)

    yield

    stop_scheduler()
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    from mt5.bridge import MT5Bridge
    await MT5Bridge.force_shutdown()
    await close_redis()
    from db.postgres import engine as _pg_engine
    await _pg_engine.dispose()
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
app.add_middleware(RequestLoggingMiddleware)

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
app.include_router(llm_analytics_routes.router, prefix="/api/v1/llm-analytics", tags=["llm-analytics"])
app.include_router(scheduler_routes.router, prefix="/api/v1/scheduler", tags=["scheduler"])
app.include_router(market_data_routes.router, prefix="/api/v1/market-data", tags=["market-data"])
app.include_router(news_routes.router,        prefix="/api/v1/news",        tags=["news"])
app.include_router(system_routes.router,      prefix="/api/v1/system",      tags=["system"])
app.include_router(logs_ingest_routes.router, prefix="/api/v1/logs/frontend", tags=["logs"])
app.include_router(logs_system_routes.router, prefix="/api/v1/logs/system", tags=["logs"])


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}
