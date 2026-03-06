# Storage Service Page — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Storage Admin Panel with monitoring metrics and targeted management operations for PostgreSQL, QuestDB, and Redis.

**Architecture:** New `backend/api/routes/storage.py` exposes read and delete endpoints; PostgreSQL stats come from `pg_stat_user_tables`; QuestDB stats via asyncpg wire protocol; Redis stats via existing `get_redis()`. Frontend has a 3-tab page with overview cards, table browsers, and confirmation-gated destructive actions.

**Tech Stack:** FastAPI, SQLAlchemy `text()`, asyncpg, redis.asyncio, Next.js, shadcn/ui (Sheet, Dialog, Tabs, Card), lucide-react.

---

## Task 1: Backend — PostgreSQL endpoints in `storage.py`

**Files:**
- Create: `backend/api/routes/storage.py`
- Test: `backend/tests/test_storage_postgres.py`

### Step 1: Write failing tests

Create `backend/tests/test_storage_postgres.py`:

```python
"""Tests for storage API — PostgreSQL section."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from main import app


@pytest.mark.anyio
async def test_get_postgres_overview_returns_shape():
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (
        "PostgreSQL 16.0",   # version
        "14 MB",             # db_size
        5,                   # connections
    )
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.storage.get_db", return_value=mock_db):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/postgres/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "db_size" in data
    assert "connections" in data


@pytest.mark.anyio
async def test_truncate_protected_table_returns_403():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete("/api/v1/storage/postgres/tables/accounts/truncate")
    assert resp.status_code == 403
    assert "protected" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_truncate_unknown_table_returns_404():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete(
            "/api/v1/storage/postgres/tables/nonexistent_table/truncate"
        )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_purge_protected_table_returns_403():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete(
            "/api/v1/storage/postgres/tables/trades/purge?older_than_days=30"
        )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_purge_older_than_days_minimum_is_1():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete(
            "/api/v1/storage/postgres/tables/pipeline_runs/purge?older_than_days=0"
        )
    assert resp.status_code == 422  # Pydantic validation error
```

### Step 2: Run tests — verify they fail

```bash
cd backend
uv run pytest tests/test_storage_postgres.py -v
```
Expected: `ImportError` or `404` on routes — module doesn't exist yet.

### Step 3: Create `backend/api/routes/storage.py` — PostgreSQL section

```python
"""Storage admin API — metrics and management for PostgreSQL, QuestDB, Redis."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Safety allowlists ──────────────────────────────────────────────────────────

PROTECTED_TABLES: frozenset[str] = frozenset(
    {
        "accounts",
        "trades",
        "strategies",
        "account_strategies",
        "ai_journal",
        "llm_provider_configs",
        "task_llm_assignments",
        "hmm_model_registry",
        "alembic_version",
    }
)

# Purgeable tables and the timestamp column used to filter old rows.
PURGEABLE_TABLES: dict[str, str] = {
    "pipeline_runs": "created_at",
    "pipeline_steps": "created_at",
    "backtest_runs": "created_at",
    "backtest_trades": "entry_time",
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


# ── PostgreSQL endpoints ───────────────────────────────────────────────────────


@router.get("/postgres/overview", response_model=PostgresOverview)
async def pg_overview(db: AsyncSession = Depends(get_db)) -> PostgresOverview:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    version(),
                    pg_size_pretty(pg_database_size(current_database())),
                    (SELECT count(*) FROM pg_stat_activity
                     WHERE datname = current_database())::int
                """
            )
        )
    ).fetchone()
    return PostgresOverview(
        version=row[0].split(" ")[0] + " " + row[0].split(" ")[1],
        db_size=row[1],
        connections=row[2],
    )


@router.get("/postgres/tables", response_model=list[TableStat])
async def pg_tables(db: AsyncSession = Depends(get_db)) -> list[TableStat]:
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    tablename,
                    COALESCE(n_live_tup, 0)::int AS row_count,
                    pg_size_pretty(pg_total_relation_size(quote_ident(tablename))),
                    pg_total_relation_size(quote_ident(tablename))::int,
                    pg_size_pretty(pg_indexes_size(quote_ident(tablename))),
                    COALESCE(last_vacuum, last_autovacuum)::text
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(quote_ident(tablename)) DESC
                """
            )
        )
    ).fetchall()
    return [
        TableStat(
            name=r[0],
            row_count=r[1],
            total_size=r[2],
            total_size_bytes=r[3],
            index_size=r[4],
            last_vacuum=r[5],
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
    count_row = (
        await db.execute(text(f"SELECT count(*) FROM {table_name}"))  # noqa: S608
    ).fetchone()
    total = int(count_row[0])
    result = await db.execute(
        text(f"SELECT * FROM {table_name} LIMIT :limit OFFSET :offset"),  # noqa: S608
        {"limit": limit, "offset": offset},
    )
    col_names = list(result.keys())
    raw_rows = result.fetchall()
    serialized = [[str(v) if v is not None else None for v in row] for row in raw_rows]
    return RowsPage(
        table=table_name,
        page=page,
        limit=limit,
        total_rows=total,
        columns=col_names,
        rows=serialized,
    )


@router.delete("/postgres/tables/{table_name}/purge", response_model=PurgeResult)
async def pg_purge(
    table_name: str,
    older_than_days: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> PurgeResult:
    if table_name in PROTECTED_TABLES:
        raise HTTPException(
            status_code=403, detail=f"Table '{table_name}' is protected and cannot be purged"
        )
    if table_name not in PURGEABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    ts_col = PURGEABLE_TABLES[table_name]
    result = await db.execute(
        text(
            f"DELETE FROM {table_name} "  # noqa: S608
            f"WHERE {ts_col} < NOW() - INTERVAL ':days days'"
        ),
        {"days": older_than_days},
    )
    await db.commit()
    deleted = result.rowcount if result.rowcount is not None else 0
    logger.info("Purged %d rows from %s (older than %d days)", deleted, table_name, older_than_days)
    return PurgeResult(table=table_name, deleted_rows=deleted, older_than_days=older_than_days)


@router.delete("/postgres/tables/{table_name}/truncate", response_model=TruncateResult)
async def pg_truncate(
    table_name: str,
    db: AsyncSession = Depends(get_db),
) -> TruncateResult:
    if table_name in PROTECTED_TABLES:
        raise HTTPException(
            status_code=403, detail=f"Table '{table_name}' is protected and cannot be truncated"
        )
    if table_name not in PURGEABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    await db.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE"))  # noqa: S608
    await db.commit()
    logger.info("Truncated table: %s", table_name)
    return TruncateResult(table=table_name, message=f"Table '{table_name}' truncated successfully")
```

### Step 4: Run tests — verify they pass

```bash
cd backend
uv run pytest tests/test_storage_postgres.py -v
```
Expected: all 5 tests pass.

---

## Task 2: Backend — QuestDB endpoints in `storage.py`

**Files:**
- Modify: `backend/api/routes/storage.py` (add QuestDB section)
- Modify: `backend/db/questdb.py` (add `get_conn()` public alias)
- Test: `backend/tests/test_storage_questdb.py`

### Step 1: Add public `get_conn()` to `backend/db/questdb.py`

At the bottom of the existing function block (after `_get_conn`), add:

```python
async def get_conn() -> asyncpg.Connection:
    """Public connection factory for use outside db/questdb.py (e.g. storage routes)."""
    return await _get_conn()
```

### Step 2: Write failing tests

Create `backend/tests/test_storage_questdb.py`:

```python
"""Tests for storage API — QuestDB section."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from main import app


@pytest.mark.anyio
async def test_questdb_tables_returns_list():
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {"name": "equity_snapshots"},
        {"name": "ohlcv_eurusd_m15"},
    ])
    mock_conn.fetchval = AsyncMock(return_value=1000)
    mock_conn.close = AsyncMock()

    with patch("api.routes.storage.questdb_get_conn", return_value=mock_conn):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/questdb/tables")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_questdb_drop_unknown_table_returns_404():
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[{"name": "equity_snapshots"}])
    mock_conn.close = AsyncMock()

    with patch("api.routes.storage.questdb_get_conn", return_value=mock_conn):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/v1/storage/questdb/tables/nonexistent")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_questdb_unreachable_returns_503():
    with patch(
        "api.routes.storage.questdb_get_conn",
        side_effect=Exception("connection refused"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/questdb/tables")
    assert resp.status_code == 503
```

### Step 3: Run tests — verify they fail

```bash
cd backend
uv run pytest tests/test_storage_questdb.py -v
```
Expected: `ImportError` or route 404 — QuestDB section not added yet.

### Step 4: Add QuestDB section to `backend/api/routes/storage.py`

Add these imports at the top of storage.py:

```python
import asyncpg
from db.questdb import get_conn as questdb_get_conn
```

Add these models after the existing Pydantic models:

```python
class QuestDBTableStat(BaseModel):
    name: str
    row_count: int


class QuestDBRowsPage(BaseModel):
    table: str
    page: int
    limit: int
    columns: list[str]
    rows: list[list]


class DropResult(BaseModel):
    table: str
    message: str
```

Add QuestDB endpoints after the PostgreSQL section:

```python
# ── QuestDB endpoints ──────────────────────────────────────────────────────────


async def _questdb_list_tables(conn: asyncpg.Connection) -> list[str]:
    """Return list of all table names from QuestDB."""
    rows = await conn.fetch("SELECT name FROM tables() ORDER BY name")
    return [r["name"] for r in rows]


@router.get("/questdb/tables", response_model=list[QuestDBTableStat])
async def qdb_tables() -> list[QuestDBTableStat]:
    try:
        conn = await questdb_get_conn()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    try:
        names = await _questdb_list_tables(conn)
        result = []
        for name in names:
            try:
                count = await conn.fetchval(f"SELECT count() FROM \"{name}\"")  # noqa: S608
            except Exception:
                count = 0
            result.append(QuestDBTableStat(name=name, row_count=int(count or 0)))
        return result
    finally:
        await conn.close()


@router.get("/questdb/tables/{table_name}/rows", response_model=QuestDBRowsPage)
async def qdb_table_rows(
    table_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> QuestDBRowsPage:
    try:
        conn = await questdb_get_conn()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    try:
        live_tables = await _questdb_list_tables(conn)
        if table_name not in live_tables:
            raise HTTPException(status_code=404, detail=f"QuestDB table '{table_name}' not found")
        offset = (page - 1) * limit
        rows = await conn.fetch(
            f"SELECT * FROM \"{table_name}\" LIMIT {limit} OFFSET {offset}"  # noqa: S608
        )
        if not rows:
            return QuestDBRowsPage(
                table=table_name, page=page, limit=limit, columns=[], rows=[]
            )
        col_names = list(rows[0].keys())
        serialized = [[str(v) if v is not None else None for v in row.values()] for row in rows]
        return QuestDBRowsPage(
            table=table_name, page=page, limit=limit, columns=col_names, rows=serialized
        )
    finally:
        await conn.close()


@router.delete("/questdb/tables/{table_name}", response_model=DropResult)
async def qdb_drop_table(table_name: str) -> DropResult:
    try:
        conn = await questdb_get_conn()
    except Exception as exc:
        logger.warning("QuestDB unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="QuestDB unreachable")
    try:
        live_tables = await _questdb_list_tables(conn)
        if table_name not in live_tables:
            raise HTTPException(status_code=404, detail=f"QuestDB table '{table_name}' not found")
        await conn.execute(f"DROP TABLE \"{table_name}\"")  # noqa: S608
        logger.info("Dropped QuestDB table: %s", table_name)
        return DropResult(table=table_name, message=f"Table '{table_name}' dropped")
    finally:
        await conn.close()
```

### Step 5: Run tests — verify they pass

```bash
cd backend
uv run pytest tests/test_storage_questdb.py -v
```
Expected: all 3 tests pass.

---

## Task 3: Backend — Redis endpoints in `storage.py`

**Files:**
- Modify: `backend/api/routes/storage.py` (add Redis section)
- Test: `backend/tests/test_storage_redis.py`

### Step 1: Write failing tests

Create `backend/tests/test_storage_redis.py`:

```python
"""Tests for storage API — Redis section."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from main import app


@pytest.mark.anyio
async def test_redis_info_returns_shape():
    mock_redis = AsyncMock()
    mock_redis.info = AsyncMock(return_value={
        "used_memory_human": "1.50M",
        "connected_clients": 3,
        "uptime_in_seconds": 3600,
        "redis_version": "7.0.15",
        "keyspace_hits": 100,
        "keyspace_misses": 10,
    })
    mock_redis.dbsize = AsyncMock(return_value=5)

    with patch("api.routes.storage.get_redis", return_value=mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/redis/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "7.0.15"
    assert data["key_count"] == 5
    assert "memory_used" in data


@pytest.mark.anyio
async def test_redis_unreachable_returns_503():
    mock_redis = AsyncMock()
    mock_redis.info = AsyncMock(side_effect=Exception("connection refused"))

    with patch("api.routes.storage.get_redis", return_value=mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/redis/info")
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_redis_flush_calls_flushdb():
    mock_redis = AsyncMock()
    mock_redis.flushdb = AsyncMock(return_value=True)

    with patch("api.routes.storage.get_redis", return_value=mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/v1/storage/redis/flush")
    assert resp.status_code == 200
    mock_redis.flushdb.assert_awaited_once()
```

### Step 2: Run tests — verify they fail

```bash
cd backend
uv run pytest tests/test_storage_redis.py -v
```

### Step 3: Add Redis section to `backend/api/routes/storage.py`

Add import at top of storage.py:

```python
from db.redis import get_redis
```

Add models:

```python
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
```

Add endpoints:

```python
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
```

### Step 4: Run tests — verify they pass

```bash
cd backend
uv run pytest tests/test_storage_redis.py -v
```

---

## Task 4: Backend — Register router in `main.py`

**Files:**
- Modify: `backend/main.py`

### Step 1: Add import and router registration

In `backend/main.py`, add import alongside the other route imports:

```python
from api.routes import storage as storage_routes
```

Add router registration after the last `app.include_router` line:

```python
app.include_router(storage_routes.router, prefix="/api/v1/storage", tags=["storage"])
```

### Step 2: Verify with a quick smoke test

```bash
cd backend
uv run uvicorn main:app --port 8000 &
curl http://localhost:8000/api/v1/storage/postgres/overview
# Expected: JSON with version, db_size, connections
curl http://localhost:8000/api/v1/storage/redis/info
# Expected: JSON with status "ok" or "unreachable" (503)
kill %1
```

### Step 3: Run all storage tests together

```bash
cd backend
uv run pytest tests/test_storage_postgres.py tests/test_storage_questdb.py tests/test_storage_redis.py -v
```
Expected: all tests pass.

---

## Task 5: Frontend — TypeScript types

**Files:**
- Create: `frontend/src/types/storage.ts`

### Step 1: Create the types file

```typescript
// Storage admin panel — API response types

export interface PostgresOverview {
  version: string;
  db_size: string;
  connections: number;
}

export interface TableStat {
  name: string;
  row_count: number;
  total_size: string;
  total_size_bytes: number;
  index_size: string;
  last_vacuum: string | null;
  is_protected: boolean;
}

export interface RowsPage {
  table: string;
  page: number;
  limit: number;
  total_rows: number;
  columns: string[];
  rows: (string | null)[][];
}

export interface PurgeResult {
  table: string;
  deleted_rows: number;
  older_than_days: number;
}

export interface TruncateResult {
  table: string;
  message: string;
}

export interface QuestDBTableStat {
  name: string;
  row_count: number;
}

export interface QuestDBRowsPage {
  table: string;
  page: number;
  limit: number;
  columns: string[];
  rows: (string | null)[][];
}

export interface DropResult {
  table: string;
  message: string;
}

export interface RedisInfo {
  status: "ok" | "unreachable";
  version: string | null;
  memory_used: string | null;
  key_count: number | null;
  uptime_seconds: number | null;
  hit_ratio: number | null;
}

export interface FlushResult {
  message: string;
  keys_flushed: number;
}
```

### Step 2: Verify no TypeScript errors

```bash
cd frontend
npx tsc --noEmit
```
Expected: no errors (this is a pure types file).

---

## Task 6: Frontend — `storageApi` in `api.ts`

**Files:**
- Modify: `frontend/src/lib/api.ts`

### Step 1: Append `storageApi` at end of `api.ts`

```typescript
// ── Storage Admin ─────────────────────────────────────────────────────────────

export const storageApi = {
  // PostgreSQL
  pgOverview: () =>
    apiRequest<import("@/types/storage").PostgresOverview>("/storage/postgres/overview"),

  pgTables: () =>
    apiRequest<import("@/types/storage").TableStat[]>("/storage/postgres/tables"),

  pgTableRows: (tableName: string, page = 1, limit = 50) =>
    apiRequest<import("@/types/storage").RowsPage>(
      `/storage/postgres/tables/${tableName}/rows?page=${page}&limit=${limit}`
    ),

  pgPurge: (tableName: string, olderThanDays: number) =>
    apiRequest<import("@/types/storage").PurgeResult>(
      `/storage/postgres/tables/${tableName}/purge?older_than_days=${olderThanDays}`,
      { method: "DELETE" }
    ),

  pgTruncate: (tableName: string) =>
    apiRequest<import("@/types/storage").TruncateResult>(
      `/storage/postgres/tables/${tableName}/truncate`,
      { method: "DELETE" }
    ),

  // QuestDB
  qdbTables: () =>
    apiRequest<import("@/types/storage").QuestDBTableStat[]>("/storage/questdb/tables"),

  qdbTableRows: (tableName: string, page = 1, limit = 50) =>
    apiRequest<import("@/types/storage").QuestDBRowsPage>(
      `/storage/questdb/tables/${tableName}/rows?page=${page}&limit=${limit}`
    ),

  qdbDropTable: (tableName: string) =>
    apiRequest<import("@/types/storage").DropResult>(
      `/storage/questdb/tables/${tableName}`,
      { method: "DELETE" }
    ),

  // Redis
  redisInfo: () =>
    apiRequest<import("@/types/storage").RedisInfo>("/storage/redis/info"),

  redisFlush: () =>
    apiRequest<import("@/types/storage").FlushResult>("/storage/redis/flush", {
      method: "DELETE",
    }),
};
```

### Step 2: Verify no TypeScript errors

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 7: Frontend — `ConfirmDestructiveDialog`

**Files:**
- Create: `frontend/src/components/storage/confirm-destructive-dialog.tsx`

### Step 1: Create the component

```tsx
"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmText: string; // text user must type to enable the button
  actionLabel: string; // button label e.g. "Truncate" / "Drop" / "Flush"
  variant?: "destructive" | "default";
  onConfirm: () => Promise<void>;
}

export function ConfirmDestructiveDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText,
  actionLabel,
  variant = "destructive",
  onConfirm,
}: Props) {
  const [typed, setTyped] = useState("");
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } finally {
      setLoading(false);
      setTyped("");
    }
  };

  const handleOpenChange = (v: boolean) => {
    if (!v) setTyped("");
    onOpenChange(v);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2 py-2">
          <Label htmlFor="confirm-input">
            Type <span className="font-mono font-semibold">{confirmText}</span> to confirm
          </Label>
          <Input
            id="confirm-input"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={confirmText}
            autoComplete="off"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant={variant}
            disabled={typed !== confirmText || loading}
            onClick={handleConfirm}
          >
            {loading ? "Working…" : actionLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 8: Frontend — `TableBrowserSheet`

**Files:**
- Create: `frontend/src/components/storage/table-browser-sheet.tsx`

### Step 1: Create the component

```tsx
"use client";

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { storageApi } from "@/lib/api";
import type { RowsPage, QuestDBRowsPage } from "@/types/storage";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tableName: string;
  system: "postgres" | "questdb";
}

type PageData = RowsPage | QuestDBRowsPage;

export function TableBrowserSheet({ open, onOpenChange, tableName, system }: Props) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PageData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !tableName) return;
    setLoading(true);
    setError(null);
    const fetch =
      system === "postgres"
        ? storageApi.pgTableRows(tableName, page)
        : storageApi.qdbTableRows(tableName, page);
    fetch
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [open, tableName, system, page]);

  const totalRows = data && "total_rows" in data ? data.total_rows : null;
  const totalPages = totalRows != null ? Math.ceil(totalRows / 50) : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full max-w-4xl overflow-y-auto">
        <SheetHeader className="mb-4">
          <SheetTitle className="flex items-center gap-2">
            {tableName}
            <Badge variant="outline">{system === "postgres" ? "PostgreSQL" : "QuestDB"}</Badge>
          </SheetTitle>
        </SheetHeader>

        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{error}</p>}

        {data && data.rows.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="border-b bg-muted/50">
                    {data.columns.map((col) => (
                      <th key={col} className="px-2 py-1 text-left font-medium whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={i} className="border-b hover:bg-muted/30">
                      {row.map((cell, j) => (
                        <td
                          key={j}
                          className="px-2 py-1 max-w-[200px] truncate text-muted-foreground"
                          title={cell ?? "null"}
                        >
                          {cell ?? <span className="italic opacity-40">null</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {totalRows != null
                  ? `Showing ${(page - 1) * 50 + 1}–${Math.min(page * 50, totalRows)} of ${totalRows.toLocaleString()} rows`
                  : `Page ${page}`}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={totalPages != null ? page >= totalPages : data.rows.length < 50}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}

        {data && data.rows.length === 0 && (
          <p className="text-sm text-muted-foreground">Table is empty.</p>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 9: Frontend — `StorageOverviewCards`

**Files:**
- Create: `frontend/src/components/storage/storage-overview-cards.tsx`

### Step 1: Create the component

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PostgresOverview, QuestDBTableStat, RedisInfo } from "@/types/storage";

interface Props {
  pgOverview: PostgresOverview | null;
  pgLoading: boolean;
  qdbTables: QuestDBTableStat[] | null;
  qdbLoading: boolean;
  redisInfo: RedisInfo | null;
  redisLoading: boolean;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
    />
  );
}

export function StorageOverviewCards({
  pgOverview,
  pgLoading,
  qdbTables,
  qdbLoading,
  redisInfo,
  redisLoading,
}: Props) {
  const qdbRowTotal = qdbTables?.reduce((sum, t) => sum + t.row_count, 0) ?? 0;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {/* PostgreSQL */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm font-medium">
            PostgreSQL
            <StatusDot ok={!!pgOverview} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {pgLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : pgOverview ? (
            <>
              <p className="text-2xl font-semibold">{pgOverview.db_size}</p>
              <p className="text-muted-foreground">{pgOverview.version}</p>
              <p className="text-muted-foreground">{pgOverview.connections} connections</p>
            </>
          ) : (
            <p className="text-destructive text-xs">Unreachable</p>
          )}
        </CardContent>
      </Card>

      {/* QuestDB */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm font-medium">
            QuestDB
            <StatusDot ok={!!qdbTables} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {qdbLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : qdbTables ? (
            <>
              <p className="text-2xl font-semibold">{qdbTables.length} tables</p>
              <p className="text-muted-foreground">{qdbRowTotal.toLocaleString()} total rows</p>
            </>
          ) : (
            <p className="text-destructive text-xs">Unreachable</p>
          )}
        </CardContent>
      </Card>

      {/* Redis */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm font-medium">
            Redis
            <StatusDot ok={redisInfo?.status === "ok"} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {redisLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : redisInfo?.status === "ok" ? (
            <>
              <p className="text-2xl font-semibold">{redisInfo.key_count} keys</p>
              <p className="text-muted-foreground">{redisInfo.memory_used} used</p>
              <p className="text-muted-foreground">v{redisInfo.version}</p>
            </>
          ) : (
            <p className="text-destructive text-xs">Unreachable</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 10: Frontend — `PostgresPanel`

**Files:**
- Create: `frontend/src/components/storage/postgres-panel.tsx`

### Step 1: Create the component

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronDown, Lock } from "lucide-react";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { TableStat } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";
import { TableBrowserSheet } from "./table-browser-sheet";

interface Props {
  tables: TableStat[];
  onRefresh: () => void;
}

type Action =
  | { kind: "truncate"; table: string }
  | { kind: "purge"; table: string; days: number };

export function PostgresPanel({ tables, onRefresh }: Props) {
  const [pendingAction, setPendingAction] = useState<Action | null>(null);
  const [browserTable, setBrowserTable] = useState<string | null>(null);

  const handleConfirm = async () => {
    if (!pendingAction) return;
    try {
      if (pendingAction.kind === "truncate") {
        const res = await storageApi.pgTruncate(pendingAction.table);
        toast.success(res.message);
      } else {
        const res = await storageApi.pgPurge(pendingAction.table, pendingAction.days);
        toast.success(`Purged ${res.deleted_rows.toLocaleString()} rows from ${res.table}`);
      }
      onRefresh();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Operation failed");
      throw e; // re-throw so dialog stays open
    }
  };

  const purgeable = tables.filter((t) => !t.is_protected);
  const protected_ = tables.filter((t) => t.is_protected);

  const purgeDialog = pendingAction?.kind === "purge" ? pendingAction : null;
  const truncateDialog = pendingAction?.kind === "truncate" ? pendingAction : null;

  return (
    <div className="space-y-4">
      {/* Purgeable tables */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Manageable
        </h3>
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-4 py-2 text-left font-medium">Table</th>
                <th className="px-4 py-2 text-right font-medium">Rows</th>
                <th className="px-4 py-2 text-right font-medium">Size</th>
                <th className="px-4 py-2 text-right font-medium">Index</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {purgeable.map((t) => (
                <tr key={t.name} className="border-b last:border-0 hover:bg-muted/20">
                  <td
                    className="cursor-pointer px-4 py-2 font-mono text-xs hover:underline"
                    onClick={() => setBrowserTable(t.name)}
                  >
                    {t.name}
                  </td>
                  <td className="px-4 py-2 text-right">{t.row_count.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right text-muted-foreground">{t.total_size}</td>
                  <td className="px-4 py-2 text-right text-muted-foreground">{t.index_size}</td>
                  <td className="px-4 py-2 text-right">
                    <div className="flex justify-end gap-2">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" size="sm">
                            Purge <ChevronDown className="ml-1 h-3 w-3" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {[30, 60, 90].map((days) => (
                            <DropdownMenuItem
                              key={days}
                              onClick={() =>
                                setPendingAction({ kind: "purge", table: t.name, days })
                              }
                            >
                              Older than {days} days
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setPendingAction({ kind: "truncate", table: t.name })}
                      >
                        Truncate
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Protected tables */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Protected (read-only)
        </h3>
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-4 py-2 text-left font-medium">Table</th>
                <th className="px-4 py-2 text-right font-medium">Rows</th>
                <th className="px-4 py-2 text-right font-medium">Size</th>
                <th className="px-4 py-2 text-right font-medium">Index</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {protected_.map((t) => (
                <tr key={t.name} className="border-b last:border-0 hover:bg-muted/20">
                  <td
                    className="cursor-pointer px-4 py-2 font-mono text-xs hover:underline"
                    onClick={() => setBrowserTable(t.name)}
                  >
                    {t.name}
                  </td>
                  <td className="px-4 py-2 text-right">{t.row_count.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right text-muted-foreground">{t.total_size}</td>
                  <td className="px-4 py-2 text-right text-muted-foreground">{t.index_size}</td>
                  <td className="px-4 py-2 text-right">
                    <Badge variant="outline" className="gap-1">
                      <Lock className="h-3 w-3" /> Protected
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Dialogs */}
      {truncateDialog && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => { if (!v) setPendingAction(null); }}
          title={`Truncate "${truncateDialog.table}"?`}
          description={`This will permanently delete ALL rows from ${truncateDialog.table}. This cannot be undone.`}
          confirmText={truncateDialog.table}
          actionLabel="Truncate"
          onConfirm={handleConfirm}
        />
      )}
      {purgeDialog && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => { if (!v) setPendingAction(null); }}
          title={`Purge "${purgeDialog.table}"?`}
          description={`Delete rows older than ${purgeDialog.days} days from ${purgeDialog.table}.`}
          confirmText={purgeDialog.table}
          actionLabel={`Purge (>${purgeDialog.days}d)`}
          onConfirm={handleConfirm}
        />
      )}

      {/* Table browser */}
      <TableBrowserSheet
        open={!!browserTable}
        onOpenChange={(v) => { if (!v) setBrowserTable(null); }}
        tableName={browserTable ?? ""}
        system="postgres"
      />
    </div>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 11: Frontend — `QuestDBPanel`

**Files:**
- Create: `frontend/src/components/storage/questdb-panel.tsx`

### Step 1: Create the component

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { QuestDBTableStat } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";
import { TableBrowserSheet } from "./table-browser-sheet";

interface Props {
  tables: QuestDBTableStat[];
  onRefresh: () => void;
}

export function QuestDBPanel({ tables, onRefresh }: Props) {
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [browserTable, setBrowserTable] = useState<string | null>(null);

  const handleDrop = async () => {
    if (!dropTarget) return;
    try {
      const res = await storageApi.qdbDropTable(dropTarget);
      toast.success(res.message);
      onRefresh();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Drop failed");
      throw e;
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th className="px-4 py-2 text-left font-medium">Table</th>
              <th className="px-4 py-2 text-right font-medium">Rows</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {tables.length === 0 && (
              <tr>
                <td colSpan={3} className="px-4 py-6 text-center text-muted-foreground text-sm">
                  No QuestDB tables found.
                </td>
              </tr>
            )}
            {tables.map((t) => (
              <tr key={t.name} className="border-b last:border-0 hover:bg-muted/20">
                <td
                  className="cursor-pointer px-4 py-2 font-mono text-xs hover:underline"
                  onClick={() => setBrowserTable(t.name)}
                >
                  {t.name}
                </td>
                <td className="px-4 py-2 text-right">{t.row_count.toLocaleString()}</td>
                <td className="px-4 py-2 text-right">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDropTarget(t.name)}
                  >
                    Drop
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dropTarget && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => { if (!v) setDropTarget(null); }}
          title={`Drop "${dropTarget}"?`}
          description={`This will permanently drop the QuestDB table "${dropTarget}" and all its data. The table will be recreated on next app startup if it is a core table.`}
          confirmText={dropTarget}
          actionLabel="Drop Table"
          onConfirm={handleDrop}
        />
      )}

      <TableBrowserSheet
        open={!!browserTable}
        onOpenChange={(v) => { if (!v) setBrowserTable(null); }}
        tableName={browserTable ?? ""}
        system="questdb"
      />
    </div>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 12: Frontend — `RedisPanel`

**Files:**
- Create: `frontend/src/components/storage/redis-panel.tsx`

### Step 1: Create the component

```tsx
"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { RedisInfo } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";

interface Props {
  info: RedisInfo | null;
  onRefresh: () => void;
}

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium">{value ?? "—"}</p>
    </div>
  );
}

export function RedisPanel({ info, onRefresh }: Props) {
  const [flushOpen, setFlushOpen] = useState(false);

  const handleFlush = async () => {
    const res = await storageApi.redisFlush();
    toast.success(`Redis flushed — ${res.keys_flushed} keys deleted`);
    onRefresh();
  };

  const unavailable = !info || info.status !== "ok";

  const uptimeDisplay =
    info?.uptime_seconds != null
      ? `${Math.floor(info.uptime_seconds / 3600)}h ${Math.floor((info.uptime_seconds % 3600) / 60)}m`
      : null;

  const hitRatioDisplay =
    info?.hit_ratio != null ? `${(info.hit_ratio * 100).toFixed(1)}%` : null;

  return (
    <div className="space-y-6">
      {unavailable && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="pt-4 text-sm text-destructive">
            Redis is unreachable. Check that the Redis container is running.
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Stat label="Version" value={info?.version ?? null} />
        <Stat label="Keys" value={info?.key_count ?? null} />
        <Stat label="Memory Used" value={info?.memory_used ?? null} />
        <Stat label="Uptime" value={uptimeDisplay} />
        <Stat label="Hit Ratio" value={hitRatioDisplay} />
      </div>

      <div className="pt-4 border-t">
        <p className="text-sm text-muted-foreground mb-3">
          Flush deletes all keys in the current Redis database (FLUSHDB). Rate-limit
          counters and OHLCV cache will be cleared.
        </p>
        <Button
          variant="destructive"
          disabled={unavailable}
          onClick={() => setFlushOpen(true)}
        >
          Flush DB
        </Button>
      </div>

      <ConfirmDestructiveDialog
        open={flushOpen}
        onOpenChange={setFlushOpen}
        title="Flush Redis DB?"
        description={`This will delete all ${info?.key_count ?? 0} keys in the current Redis database. Rate-limit counters and OHLCV cache will be cleared.`}
        confirmText="FLUSH"
        actionLabel="Flush"
        onConfirm={handleFlush}
      />
    </div>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 13: Frontend — `storage/page.tsx`

**Files:**
- Create: `frontend/src/app/storage/page.tsx`

### Step 1: Create the page

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type {
  PostgresOverview,
  TableStat,
  QuestDBTableStat,
  RedisInfo,
} from "@/types/storage";
import { StorageOverviewCards } from "@/components/storage/storage-overview-cards";
import { PostgresPanel } from "@/components/storage/postgres-panel";
import { QuestDBPanel } from "@/components/storage/questdb-panel";
import { RedisPanel } from "@/components/storage/redis-panel";

export default function StoragePage() {
  const [pgOverview, setPgOverview] = useState<PostgresOverview | null>(null);
  const [pgTables, setPgTables] = useState<TableStat[]>([]);
  const [pgLoading, setPgLoading] = useState(true);

  const [qdbTables, setQdbTables] = useState<QuestDBTableStat[]>([]);
  const [qdbLoading, setQdbLoading] = useState(true);

  const [redisInfo, setRedisInfo] = useState<RedisInfo | null>(null);
  const [redisLoading, setRedisLoading] = useState(true);

  const fetchPostgres = useCallback(async () => {
    setPgLoading(true);
    try {
      const [overview, tables] = await Promise.all([
        storageApi.pgOverview(),
        storageApi.pgTables(),
      ]);
      setPgOverview(overview);
      setPgTables(tables);
    } catch (e: unknown) {
      toast.error("Failed to load PostgreSQL data");
      setPgOverview(null);
    } finally {
      setPgLoading(false);
    }
  }, []);

  const fetchQuestDB = useCallback(async () => {
    setQdbLoading(true);
    try {
      const tables = await storageApi.qdbTables();
      setQdbTables(tables);
    } catch {
      setQdbTables([]);
    } finally {
      setQdbLoading(false);
    }
  }, []);

  const fetchRedis = useCallback(async () => {
    setRedisLoading(true);
    try {
      const info = await storageApi.redisInfo();
      setRedisInfo(info);
    } catch {
      setRedisInfo({ status: "unreachable", version: null, memory_used: null, key_count: null, uptime_seconds: null, hit_ratio: null });
    } finally {
      setRedisLoading(false);
    }
  }, []);

  const refreshAll = useCallback(() => {
    fetchPostgres();
    fetchQuestDB();
    fetchRedis();
  }, [fetchPostgres, fetchQuestDB, fetchRedis]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Storage</h1>
          <p className="text-sm text-muted-foreground">
            Monitor and manage PostgreSQL, QuestDB, and Redis
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refreshAll}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <StorageOverviewCards
        pgOverview={pgOverview}
        pgLoading={pgLoading}
        qdbTables={qdbTables}
        qdbLoading={qdbLoading}
        redisInfo={redisInfo}
        redisLoading={redisLoading}
      />

      <Tabs defaultValue="postgres">
        <TabsList>
          <TabsTrigger value="postgres">PostgreSQL</TabsTrigger>
          <TabsTrigger value="questdb">QuestDB</TabsTrigger>
          <TabsTrigger value="redis">Redis</TabsTrigger>
        </TabsList>

        <TabsContent value="postgres" className="mt-4">
          {pgLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <PostgresPanel tables={pgTables} onRefresh={fetchPostgres} />
          )}
        </TabsContent>

        <TabsContent value="questdb" className="mt-4">
          {qdbLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <QuestDBPanel tables={qdbTables} onRefresh={fetchQuestDB} />
          )}
        </TabsContent>

        <TabsContent value="redis" className="mt-4">
          {redisLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <RedisPanel info={redisInfo} onRefresh={fetchRedis} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

### Step 2: Verify TypeScript

```bash
cd frontend
npx tsc --noEmit
```

---

## Task 14: Frontend — Add Storage to sidebar

**Files:**
- Modify: `frontend/src/components/app-sidebar.tsx`

### Step 1: Add `Database` to lucide-react import

In `app-sidebar.tsx`, change the import line from:
```tsx
import {
  BarChart3,
  Brain,
  Cpu,
  FlaskConical,
  LayoutDashboard,
  ScrollText,
  Settings,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";
```
to:
```tsx
import {
  BarChart3,
  Brain,
  Cpu,
  Database,
  FlaskConical,
  LayoutDashboard,
  ScrollText,
  Settings,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";
```

### Step 2: Add Storage to `navItems`

Add after the `Pipeline Logs` entry in `navItems`:

```tsx
{ title: "Storage", url: "/storage", icon: Database },
```

Full updated array:
```tsx
const navItems = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard },
  { title: "Accounts", url: "/accounts", icon: Users },
  { title: "Strategies", url: "/strategies", icon: Cpu },
  { title: "Trades", url: "/trades", icon: TrendingUp },
  { title: "AI Signals", url: "/signals", icon: Brain },
  { title: "Pipeline Logs", url: "/logs", icon: ScrollText },
  { title: "Storage", url: "/storage", icon: Database },
  { title: "Backtest", url: "/backtest", icon: FlaskConical },
  { title: "Analytics", url: "/analytics", icon: BarChart3 },
];
```

### Step 3: Verify TypeScript and dev server

```bash
cd frontend
npx tsc --noEmit
npm run dev
# Open http://localhost:3000/storage — should render the Storage page
```

---

## Final verification

```bash
# Backend — all storage tests
cd backend
uv run pytest tests/test_storage_postgres.py tests/test_storage_questdb.py tests/test_storage_redis.py -v

# Frontend — no type errors
cd frontend
npx tsc --noEmit
```
