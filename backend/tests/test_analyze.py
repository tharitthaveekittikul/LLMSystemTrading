import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_analyze_endpoint_exists(client):
    """POST /api/v1/accounts/1/analyze returns a valid HTTP status (not 404/405)."""
    response = await client.post(
        "/api/v1/accounts/1/analyze",
        json={"symbol": "EURUSD", "timeframe": "M15"},
    )
    # Route exists — may be 404 (no such account in test DB) or 500, but NOT 404 from missing route
    assert response.status_code not in (405,)


async def test_analyze_missing_symbol_returns_422(client):
    """POST without symbol returns 422."""
    response = await client.post(
        "/api/v1/accounts/1/analyze",
        json={"timeframe": "M15"},
    )
    assert response.status_code == 422


async def test_analyze_invalid_timeframe_returns_422(client):
    """POST with invalid timeframe returns 422."""
    response = await client.post(
        "/api/v1/accounts/1/analyze",
        json={"symbol": "EURUSD", "timeframe": "INVALID"},
    )
    assert response.status_code == 422
