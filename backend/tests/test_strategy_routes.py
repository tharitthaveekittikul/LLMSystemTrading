import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_list_strategies_route_exists(client):
    """GET /strategies returns 200 or 500 (DB), never 404."""
    resp = await client.get("/api/v1/strategies")
    assert resp.status_code != 404
    assert resp.status_code != 405


async def test_create_strategy_validation(client):
    """POST /strategies with missing required fields returns 422."""
    resp = await client.post("/api/v1/strategies", json={})
    assert resp.status_code == 422


async def test_create_strategy_valid_body_accepted(client):
    """POST /strategies with valid body is not rejected for validation (200/201/409/500 all ok)."""
    body = {
        "name": "Test M15",
        "strategy_type": "config",
        "trigger_type": "candle_close",
        "symbols": ["EURUSD"],
        "timeframe": "M15",
    }
    resp = await client.post("/api/v1/strategies", json=body)
    assert resp.status_code in (201, 409, 500)
    if resp.status_code == 201:
        strategy_id = resp.json()["id"]
        await client.delete(f"/api/v1/strategies/{strategy_id}")


async def test_get_nonexistent_strategy(client):
    """GET /strategies/99999 returns 404 or 500."""
    resp = await client.get("/api/v1/strategies/99999")
    assert resp.status_code in (404, 500)


async def test_delete_nonexistent_strategy(client):
    """DELETE /strategies/99999 returns 404 or 500."""
    resp = await client.delete("/api/v1/strategies/99999")
    assert resp.status_code in (404, 500)
