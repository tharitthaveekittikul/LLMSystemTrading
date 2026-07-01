"""Shared helpers for building AccountResponse from an Account row."""
import json

from api.routes.accounts._schemas import AccountResponse
from db.models import Account


def _parse_symbols(raw: str) -> list[str]:
    try:
        return json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []


def _to_response(a: Account) -> AccountResponse:
    return AccountResponse(
        id=a.id,
        name=a.name,
        broker=a.broker,
        login=a.login,
        server=a.server,
        is_live=a.is_live,
        is_active=a.is_active,
        allowed_symbols=_parse_symbols(a.allowed_symbols),
        max_lot_size=a.max_lot_size,
        risk_pct=a.risk_pct,
        auto_trade_enabled=a.auto_trade_enabled,
        mt5_path=a.mt5_path or "",
        account_type=a.account_type or "USD",
        created_at=a.created_at,
    )


