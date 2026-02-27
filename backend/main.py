import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import accounts, analytics, trades, ws
from api.routes import signals
from api.routes import status
from api.routes import kill_switch as kill_switch_routes
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

    from services.equity_poller import run_equity_poller
    poller_task = asyncio.create_task(run_equity_poller())
    logger.info("Equity poller task started")

    yield

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


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}
