"""Pre-flight risk checks run before spending LLM tokens on a group job."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Account

logger = logging.getLogger(__name__)


async def _get_primary_account(account_id: int, db) -> "Account | None":
    """Load the first/primary account for Phase 1 signal generation."""
    from db.models import Account as _Account
    return await db.get(_Account, account_id)


async def _preflight_risk_check(
    account_entries: list[tuple[int, dict]],
    symbol: str,
    db,
) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    """Check risk limits for all accounts before calling LLM.

    Returns (clear_entries, blocked_entries).
    An account is clear if neither position limit nor rate limit is exceeded.
    """
    from core.config import settings
    from core.security import decrypt as _decrypt
    from db.models import Account as _Account
    from mt5.bridge import AccountCredentials as _Creds
    from mt5.bridge import MT5Bridge as _Bridge
    from services.risk_manager import check_position_limit, check_rate_limit, load_risk_config

    risk_cfg = await load_risk_config(db)
    clear: list[tuple[int, dict]] = []
    blocked: list[tuple[int, dict]] = []

    for account_id, overrides_dict in account_entries:
        account = await db.get(_Account, account_id)
        if not account or not account.is_active:
            blocked.append((account_id, overrides_dict))
            continue

        positions: list[dict] = []
        try:
            password = _decrypt(account.password_encrypted)
            creds = _Creds(
                login=account.login, password=password,
                server=account.server, path=account.mt5_path or settings.mt5_path,
            )
            async with _Bridge(creds) as b:
                raw = await b.get_positions()
            positions = [
                {"symbol": p.get("symbol", ""), "direction": "BUY" if p.get("type") == 0 else "SELL",
                 "volume": p.get("volume", 0), "profit": p.get("profit", 0)}
                for p in raw
            ]
        except Exception as exc:
            logger.warning("Pre-flight: could not fetch positions for account %d: %s", account_id, exc)

        exceeded_pos, pos_reason = check_position_limit(positions, risk_cfg)
        if exceeded_pos:
            logger.info("Pre-flight: account %d blocked by position limit — %s", account_id, pos_reason)
            blocked.append((account_id, overrides_dict))
            continue

        # NOTE: check_rate_limit tracks trades per-symbol globally (not per-account).
        # One busy account can block others on the same symbol. This is intentional as
        # a conservative safety measure to prevent the system from over-trading a symbol.
        exceeded_rate, rate_reason = await check_rate_limit(symbol, risk_cfg, db)
        if exceeded_rate:
            logger.info("Pre-flight: account %d blocked by rate limit — %s", account_id, rate_reason)
            blocked.append((account_id, overrides_dict))
            continue

        clear.append((account_id, overrides_dict))

    return clear, blocked


