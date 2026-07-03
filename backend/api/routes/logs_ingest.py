"""Frontend error ingestion.

Captures window.onerror / unhandled promise rejections / failed fetch & WS
disconnect events from the dashboard and folds them into the same structured
JSON log pipeline as backend events, tagged source=frontend, so a frontend
crash and the backend request that triggered it show up in the same log
stream instead of only one half being visible.
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger("frontend")

_MAX_BATCH = 20
_MAX_MESSAGE_LEN = 2000
_MAX_STACK_LEN = 4000

_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class FrontendLogEntry(BaseModel):
    level: str = Field(default="error", max_length=20)
    message: str = Field(max_length=_MAX_MESSAGE_LEN)
    url: str | None = Field(default=None, max_length=500)
    stack: str | None = Field(default=None, max_length=_MAX_STACK_LEN)
    ts: str | None = None


class FrontendLogBatch(BaseModel):
    entries: list[FrontendLogEntry] = Field(max_length=_MAX_BATCH)


@router.post("")
async def ingest_frontend_logs(batch: FrontendLogBatch) -> dict:
    for entry in batch.entries:
        level = _LEVEL_MAP.get(entry.level.lower(), logging.ERROR)
        suffix = f" | stack={entry.stack[:500]}" if entry.stack else ""
        logger.log(
            level,
            "%s | url=%s%s",
            entry.message,
            entry.url or "-",
            suffix,
            extra={"source": "frontend"},
        )
    return {"received": len(batch.entries)}
