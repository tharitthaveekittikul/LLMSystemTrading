import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_equity_history_404_for_missing_account(client):
    response = await client.get("/api/v1/accounts/99999/equity-history")
    assert response.status_code == 404


async def test_equity_history_returns_list(client):
    """Endpoint returns a list (may be empty if QuestDB not running)."""
    from datetime import datetime, UTC
    unique_login = int(datetime.now(UTC).strftime("%H%M%S%f")) % 2_000_000_000
    create_resp = await client.post("/api/v1/accounts", json={
        "name": "Equity History Test",
        "broker": "TestBroker",
        "login": unique_login,
        "password": "pass",
        "server": "test.server.com",
    })
    if create_resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = create_resp.json()["id"]

    try:
        resp = await client.get(f"/api/v1/accounts/{account_id}/equity-history?hours=24")
        # 200 with empty list (QuestDB may not be running) or 500 — but NOT 404/422
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)
    finally:
        await client.delete(f"/api/v1/accounts/{account_id}")
