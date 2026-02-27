import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_list_trades_date_filter_accepted(client):
    """date_from and date_to params are accepted without error."""
    response = await client.get(
        "/api/v1/trades?date_from=2025-12-01&date_to=2025-12-31"
    )
    # 200 or 500 (DB not running in CI) but NOT 422 (validation error)
    assert response.status_code != 422


async def test_list_trades_open_only_with_date_filter_rejected(client):
    """Combining open_only=True with date filters is rejected with 400."""
    response = await client.get(
        "/api/v1/trades?open_only=true&date_from=2025-12-01"
    )
    assert response.status_code == 400
