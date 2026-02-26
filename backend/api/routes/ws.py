"""WebSocket routes for real-time dashboard updates.

Clients connect to /ws/dashboard/{account_id}.
The MT5 poller starts when the first client connects to an account
and stops when the last client disconnects.

Event format: { "event": "<event_name>", "data": { ... } }
"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services import mt5_poller

router = APIRouter()
logger = logging.getLogger(__name__)

# { account_id: [WebSocket, ...] }
_connections: dict[int, list[WebSocket]] = {}
_lock = asyncio.Lock()


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
    except WebSocketDisconnect:
        async with _lock:
            conns = _connections.get(account_id, [])
            if websocket in conns:
                conns.remove(websocket)
            is_last = len(conns) == 0

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
