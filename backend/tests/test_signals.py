import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_list_signals_returns_not_422(client):
    """GET /api/v1/signals is a valid endpoint (not 404 or 422)."""
    response = await client.get("/api/v1/signals")
    assert response.status_code not in (404, 422)


async def test_list_signals_account_filter_accepted(client):
    """account_id query param is accepted without 422."""
    response = await client.get("/api/v1/signals?account_id=1")
    assert response.status_code != 422
