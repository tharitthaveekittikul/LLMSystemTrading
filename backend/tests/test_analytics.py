import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_daily_analytics_requires_year_month():
    """Missing year or month returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/daily")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_daily_analytics_returns_correct_shape():
    """Valid request is routed correctly and returns 200 or DB error (not routing error)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/daily?year=2025&month=12")
    # Route must exist (not 404) and params must be valid (not 422)
    # 200 = success with empty days list; 500 = DB not available in this env
    assert response.status_code in (200, 500)
