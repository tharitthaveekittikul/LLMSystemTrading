import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import accounts, analytics, trades, ws
from core.config import settings
from core.logging import setup_logging
from db.postgres import init_db

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
    logger.info("Database tables ready")
    yield
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

app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["accounts"])
app.include_router(trades.router, prefix="/api/v1/trades", tags=["trades"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}
