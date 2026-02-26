from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import accounts, analytics, trades, ws
from core.config import settings
from db.postgres import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="LLM Trading System",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}
