"""Storage admin API — metrics and management for PostgreSQL, QuestDB, Redis."""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.postgres import get_db
from db.questdb import get_conn as questdb_get_conn
from db.redis import get_redis

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Safety allowlists ──────────────────────────────────────────────────────────

PROTECTED_TABLES: frozenset[str] = frozenset({
    "accounts", "trades", "strategies", "account_strategies",
    "ai_journal", "llm_provider_configs", "task_llm_assignments",
    "hmm_model_registry", "alembic_version",
    "pipeline_steps", "backtest_trades",  # child tables — cascade-only, no direct management
})

PURGEABLE_TABLES: dict[str, str] = {
    "pipeline_runs": "created_at",
    "backtest_runs": "created_at",
    "kill_switch_log": "created_at",
}

ALL_KNOWN_TABLES: frozenset[str] = PROTECTED_TABLES | frozenset(PURGEABLE_TABLES)

# ── Response models ────────────────────────────────────────────────────────────

class PostgresOverview(BaseModel):
    version: str
    db_size: str
    connections: int

class TableStat(BaseModel):
    name: str
    row_count: int
    total_size: str
    total_size_bytes: int
    index_size: str
    last_vacuum: str | None
    is_protected: bool

class RowsPage(BaseModel):
    table: str
    page: int
    limit: int
    total_rows: int
    columns: list[str]
    rows: list[list]

class PurgeResult(BaseModel):
    table: str
    deleted_rows: int
    older_than_days: int

class TruncateResult(BaseModel):
    table: str
    message: str

class QuestDBTableStat(BaseModel):
    name: str
    row_count: int

class QuestDBRowsPage(BaseModel):
    table: str
    page: int
    limit: int
    total_rows: int
    columns: list[str]
    rows: list[list]

class DropResult(BaseModel):
    table: str
    message: str

class RedisInfo(BaseModel):
    status: str  # "ok" or "unreachable"
    version: str | None = None
    memory_used: str | None = None
    key_count: int | None = None
    uptime_seconds: int | None = None
    hit_ratio: float | None = None

class FlushResult(BaseModel):
    message: str
    keys_flushed: int

# ── PostgreSQL endpoints ───────────────────────────────────────────────────────

@router.get("/postgres/overview", response_model=PostgresOverview)
async def pg_overview(db: AsyncSession = Depends(get_db)) -> PostgresOverview:
    row = (await db.execute(text("""
        SELECT
            version(),
            pg_size_pretty(pg_database_size(current_database())),
            (SELECT count(*) FROM pg_stat_activity
             WHERE datname = current_database())::int
    """))).fetchone()
    return PostgresOverview(
        version=row[0].split(",")[0],   # e.g. "PostgreSQL 16.2"
        db_size=row[1],
        connections=row[2],
    )

@router.get("/postgres/tables", response_model=list[TableStat])
async def pg_tables(db: AsyncSession = Depends(get_db)) -> list[TableStat]:
    rows = (await db.execute(text("""
        SELECT
            relname,
            COALESCE(n_live_tup, 0)::int,
            pg_size_pretty(pg_total_relation_size(relid)),
            pg_total_relation_size(relid)::int,
            pg_size_pretty(pg_indexes_size(relid)),
            COALESCE(last_vacuum, last_autovacuum)::text
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
    """))).fetchall()
    return [
        TableStat(
            name=r[0], row_count=r[1], total_size=r[2],
            total_size_bytes=r[3], index_size=r[4], last_vacuum=r[5],
            is_protected=r[0] in PROTECTED_TABLES,
        )
        for r in rows
    ]

@router.get("/postgres/tables/{table_name}/rows", response_model=RowsPage)
async def pg_table_rows(
    table_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> RowsPage:
    if table_name not in ALL_KNOWN_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    offset = (page - 1) * limit
    total = (await db.execute(text(f"SELECT count(*) FROM {table_name}"))).scalar()  # noqa: S608
    result = await db.execute(
        text(f"SELECT * FROM {table_name} LIMIT :lim OFFSET :off"),  # noqa: S608
        {"lim": limit, "off": offset},
    )
    col_names = list(result.keys())
    rows = [[str(v) if v is not None else None for v in row] for row in result.fetchall()]
    return RowsPage(table=table_name, page=page, limit=limit,
                    total_rows=int(total or 0), columns=col_names, rows=rows)

@router.delete("/postgres/tables/{table_name}/purge", response_model=PurgeResult)
async def pg_purge(
    table_name: str,
    older_than_days: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> PurgeResult:
    if table_name in PROTECTED_TABLES:
        raise HTTPException(status_code=403,
            detail=f"Table '{table_name}' is protected and cannot be purged")
    if table_name not in PURGEABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    ts_col = PURGEABLE_TABLES[table_name]
    result = await db.execute(
        text(f"DELETE FROM {table_name} WHERE {ts_col} < NOW() - (:days * INTERVAL '1 day')"),  # noqa: S608
        {"days": older_than_days},
    )
    await db.commit()
    deleted = result.rowcount or 0
    logger.info("Purged %d rows from %s (older than %d days)", deleted, table_name, older_than_days)
    return PurgeResult(table=table_name, deleted_rows=deleted, older_than_days=older_than_days)

@router.delete("/postgres/tables/{table_name}/truncate", response_model=TruncateResult)
async def pg_truncate(
    table_name: str,
    db: AsyncSession = Depends(get_db),
) -> TruncateResult:
    if table_name in PROTECTED_TABLES:
        raise HTTPException(status_code=403,
            detail=f"Table '{table_name}' is protected and cannot be truncated")
    if table_name not in PURGEABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    await db.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE"))  # noqa: S608
    await db.commit()
    logger.info("Truncated table: %s", table_name)
    return TruncateResult(table=table_name, message=f"Table '{table_name}' truncated successfully")


# ── QuestDB endpoints ──────────────────────────────────────────────────────────

def _questdb_http_url() -> str:
    return f"http://{settings.questdb_host}:{settings.questdb_http_port}/exec"


async def _questdb_list_tables() -> list[str]:
    """Return all table names from QuestDB via HTTP REST API (avoids wire-protocol limitations)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_questdb_http_url(), params={"query": "tables()"})
        resp.raise_for_status()
        data = resp.json()
        # tables() schema: id(INT), name(STRING), ... — find "name" column; default to 1
        cols = data.get("columns", [])
        name_idx = next((i for i, c in enumerate(cols) if c.get("name") == "name"), 1)
        return sorted(str(row[name_idx]) for row in data.get("dataset", []))


@router.get("/questdb/tables", response_model=list[QuestDBTableStat])
async def qdb_tables() -> list[QuestDBTableStat]:
    try:
        names = await _questdb_list_tables()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    result = []
    for name in names:
        try:
            conn = await questdb_get_conn()
            try:
                count = await conn.fetchval(f'SELECT count() FROM "{name}"')  # noqa: S608
            finally:
                await conn.close()
        except Exception:
            count = 0
        result.append(QuestDBTableStat(name=name, row_count=int(count or 0)))
    return result


@router.get("/questdb/tables/{table_name}/rows", response_model=QuestDBRowsPage)
async def qdb_table_rows(
    table_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> QuestDBRowsPage:
    try:
        live_tables = await _questdb_list_tables()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    try:
        conn = await questdb_get_conn()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    try:
        if table_name not in live_tables:
            raise HTTPException(status_code=404,
                detail=f"QuestDB table '{table_name}' not found")
        total_rows = int(await conn.fetchval(f'SELECT count() FROM "{table_name}"') or 0)  # noqa: S608
        offset = (page - 1) * limit
        rows = await conn.fetch(
            f'SELECT * FROM "{table_name}" LIMIT {offset},{offset + limit}'  # noqa: S608
        )
        if not rows:
            return QuestDBRowsPage(table=table_name, page=page, limit=limit,
                                   total_rows=total_rows, columns=[], rows=[])
        col_names = list(rows[0].keys())
        serialized = [[str(v) if v is not None else None for v in row.values()] for row in rows]
        return QuestDBRowsPage(table=table_name, page=page, limit=limit,
                               total_rows=total_rows, columns=col_names, rows=serialized)
    finally:
        await conn.close()


@router.delete("/questdb/tables/{table_name}", response_model=DropResult)
async def qdb_drop_table(table_name: str) -> DropResult:
    try:
        live_tables = await _questdb_list_tables()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    if table_name not in live_tables:
        raise HTTPException(status_code=404, detail=f"QuestDB table '{table_name}' not found")
    conn = await questdb_get_conn()
    try:
        await conn.execute(f'DROP TABLE "{table_name}"')  # noqa: S608
        logger.info("Dropped QuestDB table: %s", table_name)
        return DropResult(table=table_name, message=f"Table '{table_name}' dropped")
    finally:
        await conn.close()


# ── Redis endpoints ────────────────────────────────────────────────────────────

@router.get("/redis/info", response_model=RedisInfo)
async def redis_info() -> RedisInfo:
    r = get_redis()
    try:
        info = await r.info()
        key_count = await r.dbsize()
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        hit_ratio = round(hits / total, 4) if total > 0 else 0.0
        return RedisInfo(
            status="ok",
            version=info.get("redis_version"),
            memory_used=info.get("used_memory_human"),
            key_count=int(key_count),
            uptime_seconds=info.get("uptime_in_seconds"),
            hit_ratio=hit_ratio,
        )
    except Exception as exc:
        logger.warning("Redis unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="Redis unreachable")


@router.delete("/redis/flush", response_model=FlushResult)
async def redis_flush() -> FlushResult:
    r = get_redis()
    try:
        key_count = await r.dbsize()
        await r.flushdb()
        logger.warning("Redis FLUSHDB executed — %d keys deleted", key_count)
        return FlushResult(message="Redis DB flushed", keys_flushed=int(key_count))
    except Exception as exc:
        logger.error("Redis flush failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Redis flush failed: {exc}")
