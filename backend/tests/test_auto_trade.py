import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_account_response_includes_auto_trade_enabled(client):
    """AccountResponse schema must include auto_trade_enabled field."""
    response = await client.get("/api/v1/accounts")
    assert response.status_code != 422
    accounts = response.json()
    if accounts:
        assert "auto_trade_enabled" in accounts[0]
