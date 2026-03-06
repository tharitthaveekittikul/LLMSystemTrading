"""Tests for the PostgreSQL section of the storage admin API."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from api.routes.storage import router as storage_router


# ── Minimal test app (isolated from main.py for fast unit tests) ────────────────

def make_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(storage_router, prefix="/api/v1/storage", tags=["storage"])
    return test_app


# ── Tests 1-4: no DB needed — route guards fire before any DB access ───────────

@pytest.mark.asyncio
async def test_truncate_protected_table_returns_403():
    """DELETE /api/v1/storage/postgres/tables/accounts/truncate → 403 with 'protected' in body."""
    app = make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/v1/storage/postgres/tables/accounts/truncate")
    assert response.status_code == 403
    assert "protected" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_truncate_unknown_table_returns_404():
    """DELETE /api/v1/storage/postgres/tables/nonexistent/truncate → 404."""
    app = make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/v1/storage/postgres/tables/nonexistent/truncate")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_purge_protected_table_returns_403():
    """DELETE /api/v1/storage/postgres/tables/trades/purge?older_than_days=30 → 403."""
    app = make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            "/api/v1/storage/postgres/tables/trades/purge?older_than_days=30"
        )
    assert response.status_code == 403
    assert "protected" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_purge_requires_days_ge_1():
    """DELETE /api/v1/storage/postgres/tables/pipeline_runs/purge?older_than_days=0 → 422."""
    app = make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            "/api/v1/storage/postgres/tables/pipeline_runs/purge?older_than_days=0"
        )
    assert response.status_code == 422


# ── Test 5: mock DB to verify route exists and returns 200 ─────────────────────

@pytest.mark.asyncio
async def test_pg_tables_endpoint_exists():
    """GET /api/v1/storage/postgres/tables → not 404 or 500 (route must exist).

    The DB is mocked to return an empty result set so no real PostgreSQL
    connection is required.
    """
    app = make_test_app()

    # Build a mock AsyncSession whose execute() returns an object with fetchall()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def override_get_db():
        yield mock_db

    from api.routes import storage as storage_module
    app.dependency_overrides[storage_module.get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage/postgres/tables")

    assert response.status_code not in (404, 500)
    assert response.json() == []
