"""System status — poller health and per-account MT5 connectivity."""
import logging

from fastapi import APIRouter

from services import mt5_poller

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def get_status():
    states = mt5_poller.get_states()
    return {
        "poller_running": any(not t.done() for t in mt5_poller._tasks.values()),
        "accounts": [
            {
                "account_id": s.account_id,
                "is_connected": s.is_connected,
                "last_polled_at": s.last_polled_at.isoformat() if s.last_polled_at else None,
                "last_error": s.last_error,
            }
            for s in states.values()
        ],
    }
