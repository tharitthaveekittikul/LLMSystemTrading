"""Historical query over the structured JSON system log.

Reads backend/logs/app.jsonl (the active rotating-log file only — older
rotated backups like app.jsonl.1 are not searched, so very old entries fall
out of range once a rotation happens). This is the "Search" half of the
System Logs page; the "Live" half is a WebSocket system_log event fed by
the handler attached in core/logging.attach_websocket_log_handler().
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_LIMIT = 500


class SystemLogEntry(BaseModel):
    ts: str
    level: str
    logger: str
    message: str
    request_id: str | None = None
    run_id: int | None = None
    account_id: int | None = None
    symbol: str | None = None
    source: str | None = None


class SystemLogPage(BaseModel):
    entries: list[SystemLogEntry]
    total_matched: int
    has_more: bool


def _log_file_path() -> Path:
    return Path(settings.log_dir) / "app.jsonl"


def _read_all_entries() -> list[dict]:
    path = _log_file_path()
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed log line during query")
    return entries


@router.get("", response_model=SystemLogPage)
async def query_system_logs(
    level: str | None = Query(default=None),
    logger_name: str | None = Query(default=None, alias="logger"),
    run_id: int | None = Query(default=None),
    account_id: int | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> SystemLogPage:
    entries = _read_all_entries()
    entries.reverse()  # most recent first

    level_upper = level.upper() if level else None

    def _matches(e: dict) -> bool:
        if level_upper and e.get("level") != level_upper:
            return False
        if logger_name and logger_name not in e.get("logger", ""):
            return False
        if run_id is not None and e.get("run_id") != run_id:
            return False
        if account_id is not None and e.get("account_id") != account_id:
            return False
        if from_ts and e.get("ts", "") < from_ts:
            return False
        if to_ts and e.get("ts", "") > to_ts:
            return False
        return True

    filtered = [e for e in entries if _matches(e)]
    page = filtered[offset : offset + limit]
    return SystemLogPage(
        entries=[SystemLogEntry(**e) for e in page],
        total_matched=len(filtered),
        has_more=offset + limit < len(filtered),
    )
