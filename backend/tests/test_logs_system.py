"""Tests for GET /api/v1/logs/system (historical query) and the live-tail
WebSocket log handler (Part D).
"""
import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.routes.logs_system import _read_all_entries
from core.config import settings
from core.logging import _WebSocketLogHandler, attach_websocket_log_handler
from main import app

pytestmark = pytest.mark.asyncio


def _write_log_file(path, lines):
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


SAMPLE_LINES = [
    {"ts": "2026-07-03T13:00:00", "level": "INFO", "logger": "mt5.bridge",
     "message": "connected", "account_id": 1},
    {"ts": "2026-07-03T13:05:00", "level": "WARNING", "logger": "mt5.bridge",
     "message": "no match", "account_id": 1},
    {"ts": "2026-07-03T14:00:00", "level": "ERROR", "logger": "ai.pipeline",
     "message": "boom", "run_id": 7},
]


# ── _read_all_entries ────────────────────────────────────────────────────────

def test_read_all_entries_returns_empty_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "does-not-exist"))
    assert _read_all_entries() == []


def test_read_all_entries_skips_malformed_lines(tmp_path, monkeypatch):
    path = tmp_path / "app.jsonl"
    path.write_text('{"ts": "t", "level": "INFO", "logger": "x", "message": "ok"}\nnot json\n')
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))

    entries = _read_all_entries()
    assert len(entries) == 1
    assert entries[0]["message"] == "ok"


# ── GET /api/v1/logs/system ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_query_empty_when_no_log_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "nope"))
    resp = await client.get("/api/v1/logs/system")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"entries": [], "total_matched": 0, "has_more": False}


async def test_query_filters_by_level_and_orders_newest_first(client, tmp_path, monkeypatch):
    _write_log_file(tmp_path / "app.jsonl", SAMPLE_LINES)
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))

    resp = await client.get("/api/v1/logs/system", params={"level": "warning"})
    body = resp.json()
    assert body["total_matched"] == 1
    assert body["entries"][0]["message"] == "no match"


async def test_query_filters_by_run_id(client, tmp_path, monkeypatch):
    _write_log_file(tmp_path / "app.jsonl", SAMPLE_LINES)
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))

    resp = await client.get("/api/v1/logs/system", params={"run_id": 7})
    body = resp.json()
    assert body["total_matched"] == 1
    assert body["entries"][0]["message"] == "boom"


async def test_query_pagination_has_more(client, tmp_path, monkeypatch):
    _write_log_file(tmp_path / "app.jsonl", SAMPLE_LINES)
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))

    resp = await client.get("/api/v1/logs/system", params={"limit": 2, "offset": 0})
    body = resp.json()
    assert len(body["entries"]) == 2
    assert body["total_matched"] == 3
    assert body["has_more"] is True
    # Most recent first: the ERROR line (14:00) should be entries[0].
    assert body["entries"][0]["message"] == "boom"


# ── _WebSocketLogHandler / attach_websocket_log_handler ─────────────────────

async def test_ws_log_handler_emit_broadcasts_payload():
    loop = asyncio.get_running_loop()
    handler = _WebSocketLogHandler(loop)

    record = logging.LogRecord(
        name="mt5.bridge", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="no match", args=(), exc_info=None,
    )

    with patch("api.routes.ws.broadcast_all", new=AsyncMock()) as mock_broadcast:
        handler.emit(record)
        # emit() schedules via run_coroutine_threadsafe — give the loop a beat.
        await asyncio.sleep(0.05)

    mock_broadcast.assert_awaited_once()
    event_name, payload = mock_broadcast.call_args.args
    assert event_name == "system_log"
    assert payload["message"] == "no match"
    assert payload["logger"] == "mt5.bridge"


def test_attach_websocket_log_handler_is_idempotent():
    import core.logging as logging_module

    original = logging_module._ws_log_handler
    try:
        logging_module._ws_log_handler = None
        loop = asyncio.new_event_loop()
        try:
            attach_websocket_log_handler(loop)
            first = logging_module._ws_log_handler
            attach_websocket_log_handler(loop)
            assert logging_module._ws_log_handler is first
        finally:
            logging.getLogger().removeHandler(first)
            loop.close()
    finally:
        logging_module._ws_log_handler = original
