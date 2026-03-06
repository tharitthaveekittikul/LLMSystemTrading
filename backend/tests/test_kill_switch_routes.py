import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from main import app


@pytest.mark.asyncio
async def test_get_kill_switch_status():
    """GET /api/v1/kill-switch returns is_active field."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/kill-switch")
    assert response.status_code == 200
    data = response.json()
    assert "is_active" in data


@pytest.mark.asyncio
async def test_activate_requires_reason():
    """POST /api/v1/kill-switch/activate without reason returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/kill-switch/activate", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_deactivate_returns_200():
    """POST /api/v1/kill-switch/deactivate always succeeds (DB write is mocked)."""
    with patch("services.kill_switch._persist", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/kill-switch/deactivate")
    assert response.status_code == 200
