"""WebSocket routes for real-time dashboard updates.

Clients connect to /ws/dashboard/{account_id}.
The MT5 poller starts when the first client connects to an account
and stops when the last client disconnects.

Event format: { "event": "<event_name>", "data": { ... } }

Clients may send `{"action": "watch_symbol", "symbol": "<broker symbol>"}`
to receive periodic "tick_update" events for that symbol (e.g. a chart page
tracking live price) — see mt5_poller._fetch_and_broadcast.
"""
import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services import mt5_poller

router = APIRouter()
logger = logging.getLogger(__name__)

# { account_id: [WebSocket, ...] }
_connections: dict[int, list[WebSocket]] = {}
# { account_id: { WebSocket: symbol } } — one watched symbol per connection
_watched_symbols: dict[int, dict[WebSocket, str]] = {}
_lock = asyncio.Lock()


def get_watched_symbols(account_id: int) -> set[str]:
    """Return the distinct set of symbols any connected client is watching."""
    return set(_watched_symbols.get(account_id, {}).values())


@router.websocket("/dashboard/{account_id}")
async def dashboard_ws(websocket: WebSocket, account_id: int):
    await websocket.accept()

    async with _lock:
        _connections.setdefault(account_id, []).append(websocket)
        is_first = len(_connections[account_id]) == 1

    logger.info("WebSocket connected | account_id=%s client=%s", account_id, websocket.client)

    if is_first:
        await mt5_poller.start_account(account_id)

    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
                continue
            try:
                data = json.loads(msg)
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get("action") == "watch_symbol":
                symbol = data.get("symbol")
                async with _lock:
                    if isinstance(symbol, str) and symbol:
                        _watched_symbols.setdefault(account_id, {})[websocket] = symbol
                    else:
                        _watched_symbols.get(account_id, {}).pop(websocket, None)
    except WebSocketDisconnect:
        async with _lock:
            conns = _connections.get(account_id, [])
            if websocket in conns:
                conns.remove(websocket)
            is_last = len(conns) == 0
            _watched_symbols.get(account_id, {}).pop(websocket, None)

        logger.info("WebSocket disconnected | account_id=%s client=%s", account_id, websocket.client)

        if is_last:
            await mt5_poller.stop_account(account_id)


async def broadcast(account_id: int, event: str, data: dict[str, Any]) -> None:
    """Push an event to all dashboard clients for a specific account."""
    message = {"event": event, "data": data}
    dead: list[WebSocket] = []

    for ws in _connections.get(account_id, []):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)

    if dead:
        async with _lock:
            for ws in dead:
                conns = _connections.get(account_id, [])
                if ws in conns:
                    conns.remove(ws)


async def broadcast_all(event: str, data: dict[str, Any]) -> None:
    """Push an event to ALL connected dashboard clients (e.g. kill switch)."""
    tasks = [
        broadcast(account_id, event, data) for account_id in list(_connections.keys())
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
