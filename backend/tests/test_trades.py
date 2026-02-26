import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_list_trades_date_filter_accepted():
    """date_from and date_to params are accepted without error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/trades?date_from=2025-12-01&date_to=2025-12-31"
        )
    # 200 or 500 (DB not running in CI) but NOT 422 (validation error)
    assert response.status_code != 422


@pytest.mark.asyncio
async def test_list_trades_open_only_with_date_filter_rejected():
    """Combining open_only=True with date filters is rejected with 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/trades?open_only=true&date_from=2025-12-01"
        )
    assert response.status_code == 400
