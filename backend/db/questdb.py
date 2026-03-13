"""QuestDB client via PostgreSQL wire protocol (port 8812).

Used for time-series data: OHLCV candles, ticks, and equity snapshots.
QuestDB is append-only — never UPDATE or DELETE rows.
"""
import asyncio
import logging
import re
from datetime import UTC, datetime

import asyncpg

from core.config import settings

logger = logging.getLogger(__name__)

# Only allow lowercase alphanumerics and underscores in table-name components.
# This prevents SQL injection via symbol / timeframe inputs.
_SAFE_IDENT_RE = re.compile(r"[^a-z0-9_]")


def _safe_table_name(symbol: str, timeframe: str) -> str:
    """Return a sanitized QuestDB table name for OHLCV data."""
    sym = _SAFE_IDENT_RE.sub("_", symbol.lower())
    tf = _SAFE_IDENT_RE.sub("_", timeframe.lower())
    return f"ohlcv_{sym}_{tf}"


async def _get_conn() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=settings.questdb_host,
        port=settings.questdb_pg_port,
        database=settings.questdb_db,
        user=settings.questdb_user,
        password=settings.questdb_password,
    )


async def init_questdb() -> None:
    """Create QuestDB tables if they do not already exist. Called once on startup."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                ts TIMESTAMP,
                account_id INT,
                equity DOUBLE,
                balance DOUBLE,
                margin DOUBLE
            ) TIMESTAMP(ts) PARTITION BY DAY WAL;
            """
        )
        logger.info("QuestDB tables ready")
    except Exception as exc:
        logger.warning("QuestDB init skipped (not available): %s", exc)
    finally:
        await conn.close()


async def insert_equity_snapshot(
    account_id: int, equity: float, balance: float, margin: float
) -> None:
    """Append an equity snapshot row. Fire-and-forget safe."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO equity_snapshots (ts, account_id, equity, balance, margin)
            VALUES ($1, $2, $3, $4, $5)
            """,
            datetime.now(UTC).replace(tzinfo=None),  # QuestDB TIMESTAMP is tz-naive; strip tzinfo before passing
            account_id,
            equity,
            balance,
            margin,
        )
    finally:
        await conn.close()


async def get_equity_history(account_id: int, hours: int = 24) -> list[dict]:
    """Return equity snapshots for the last N hours. Returns [] if table is empty or missing."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT ts, equity, balance
            FROM equity_snapshots
            WHERE account_id = $1
              AND ts >= dateadd('h', -$2, now())
            ORDER BY ts ASC
            """,
            account_id,
            hours,
        )
        return [
            {"ts": str(r["ts"]), "equity": float(r["equity"]), "balance": float(r["balance"])}
            for r in rows
        ]
    except Exception as exc:
        logger.error("get_equity_history failed | account_id=%s | %s", account_id, exc)
        return []
    finally:
        await conn.close()


async def insert_ohlcv(
    symbol: str,
    timeframe: str,
    ts: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> None:
    table = _safe_table_name(symbol, timeframe)
    conn = await _get_conn()
    try:
        await conn.execute(
            f"INSERT INTO {table} (ts, open, high, low, close, volume) "
            f"VALUES ($1, $2, $3, $4, $5, $6)",
            ts, open_, high, low, close, volume,
        )
    finally:
        await conn.close()


async def get_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = 200,
) -> list[dict]:
    table = _safe_table_name(symbol, timeframe)
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            f"SELECT ts, open, high, low, close, volume FROM {table} "
            f"ORDER BY ts DESC LIMIT $1",
            limit,
        )
        return [dict(r) for r in reversed(rows)]
    except Exception as exc:
        logger.error("get_ohlcv failed for table=%s: %s", table, exc)
        return []
    finally:
        await conn.close()


def fire_and_forget(coro) -> None:
    """Schedule a coroutine as a background task (for non-blocking DB writes)."""
    asyncio.create_task(coro)


async def get_conn() -> asyncpg.Connection:
    """Public connection factory for use outside db/questdb.py (e.g. storage routes)."""
    return await _get_conn()
