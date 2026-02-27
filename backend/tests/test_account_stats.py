import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_account_stats_404_for_unknown_account(client):
    response = await client.get("/api/v1/accounts/99999/stats")
    assert response.status_code == 404


async def test_account_stats_schema(client):
    """Stats endpoint returns the expected shape (empty account = zeros)."""
    from datetime import datetime, UTC
    unique_login = int(datetime.now(UTC).strftime("%H%M%S%f")) % 2_000_000_000  # fits int32
    create_resp = await client.post("/api/v1/accounts", json={
        "name": "Stats Test",
        "broker": "TestBroker",
        "login": unique_login,
        "password": "pass",
        "server": "test.server.com",
    })
    if create_resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = create_resp.json()["id"]

    try:
        resp = await client.get(f"/api/v1/accounts/{account_id}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "win_rate" in data
        assert "total_pnl" in data
        assert "trade_count" in data
        assert "winning_trades" in data
        assert data["trade_count"] == 0
        assert data["win_rate"] == 0.0
    finally:
        await client.delete(f"/api/v1/accounts/{account_id}")
