"""Tests for the structured JSON logging backbone (Part C).

Covers: the JSON line formatter, contextvar-based correlation IDs
(CorrelationFilter + bind/clear), and the frontend error ingestion endpoint.
"""
import json
import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.log_context import CorrelationFilter, bind, clear
from core.logging import _JsonFormatter
from main import app

pytestmark = pytest.mark.asyncio


def _make_record(logger_name: str = "some.module", msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name, level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


# ── _JsonFormatter ─────────────────────────────────────────────────────────────

def test_json_formatter_produces_valid_json_with_core_fields():
    record = _make_record()
    payload = json.loads(_JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "some.module"
    assert payload["message"] == "hello"
    assert "ts" in payload


def test_json_formatter_omits_correlation_fields_when_unset():
    payload = json.loads(_JsonFormatter().format(_make_record()))

    for field in ("request_id", "run_id", "account_id", "symbol", "source"):
        assert field not in payload


def test_json_formatter_includes_correlation_fields_when_present():
    record = _make_record()
    record.run_id = 42
    record.account_id = 7
    record.source = "frontend"
    payload = json.loads(_JsonFormatter().format(record))

    assert payload["run_id"] == 42
    assert payload["account_id"] == 7
    assert payload["source"] == "frontend"


# ── bind / clear / CorrelationFilter ────────────────────────────────────────────

def test_bind_stamps_fields_via_filter_and_clear_removes_them():
    record = _make_record()
    filt = CorrelationFilter()

    tokens = bind(run_id=1, account_id=2)
    try:
        filt.filter(record)
        assert record.run_id == 1
        assert record.account_id == 2
    finally:
        clear(tokens)

    record2 = _make_record()
    filt.filter(record2)
    assert getattr(record2, "run_id", None) is None
    assert getattr(record2, "account_id", None) is None


def test_bind_unknown_field_raises():
    with pytest.raises(KeyError):
        bind(nonsense_field="x")


def test_nested_bind_restores_outer_value_on_clear():
    outer = bind(account_id=1)
    try:
        inner = bind(account_id=2)
        try:
            record = _make_record()
            CorrelationFilter().filter(record)
            assert record.account_id == 2
        finally:
            clear(inner)

        record2 = _make_record()
        CorrelationFilter().filter(record2)
        assert record2.account_id == 1
    finally:
        clear(outer)


# ── Frontend error ingestion endpoint ────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_ingest_frontend_logs_accepts_batch(client, caplog):
    payload = {
        "entries": [
            {"level": "error", "message": "TypeError: boom", "url": "/chart/XAUUSD", "stack": "at foo()"},
            {"level": "warning", "message": "WS disconnected"},
        ]
    }
    with caplog.at_level(logging.WARNING, logger="frontend"):
        resp = await client.post("/api/v1/logs/frontend", json=payload)

    assert resp.status_code == 200
    assert resp.json() == {"received": 2}
    messages = [r.message for r in caplog.records if r.name == "frontend"]
    assert any("boom" in m for m in messages)
    assert all(getattr(r, "source", None) == "frontend" for r in caplog.records if r.name == "frontend")


async def test_ingest_frontend_logs_rejects_oversized_batch(client):
    entries = [{"level": "error", "message": "x"} for _ in range(21)]
    resp = await client.post("/api/v1/logs/frontend", json={"entries": entries})
    assert resp.status_code == 422


async def test_ingest_frontend_logs_rejects_missing_message(client):
    resp = await client.post("/api/v1/logs/frontend", json={"entries": [{"level": "error"}]})
    assert resp.status_code == 422
