"""Tests for /history and /history/sync endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport


def _mock_account():
    return MagicMock(
        id=1, login=12345, password_encrypted="enc",
        server="srv", mt5_path="", is_active=True,
    )


def test_get_history_endpoint_exists():
    from main import app
    routes = [r.path for r in app.routes]
    assert any("/accounts/{account_id}/history" in r for r in routes)


def test_sync_history_endpoint_exists():
    from main import app
    routes = [r.path for r in app.routes]
    assert any("/accounts/{account_id}/history/sync" in r for r in routes)


@pytest.mark.asyncio
async def test_get_history_returns_deals():
    from main import app
    from db.postgres import get_db as real_get_db

    deals = [{"ticket": 1, "position_id": 100, "symbol": "EURUSD", "profit": 30.0}]
    mock_account = _mock_account()

    async def override_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_account
        yield mock_db

    app.dependency_overrides[real_get_db] = override_db

    with patch("api.routes.accounts.HistoryService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.get_raw_deals = AsyncMock(return_value=deals)
        mock_svc_cls.return_value = mock_svc

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/accounts/1/history?days=30")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["ticket"] == 1


@pytest.mark.asyncio
async def test_sync_history_returns_imported_count():
    from main import app
    from db.postgres import get_db as real_get_db

    mock_account = _mock_account()

    async def override_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_account
        yield mock_db

    app.dependency_overrides[real_get_db] = override_db

    with patch("api.routes.accounts.HistoryService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.sync_to_db = AsyncMock(return_value={"imported": 5, "total_fetched": 12})
        mock_svc_cls.return_value = mock_svc

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/accounts/1/history/sync")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 5
    assert data["total_fetched"] == 12


@pytest.mark.asyncio
async def test_get_history_404_when_account_not_found():
    from main import app
    from db.postgres import get_db as real_get_db

    async def override_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = None
        yield mock_db

    app.dependency_overrides[real_get_db] = override_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/accounts/999/history")

    app.dependency_overrides = {}
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sync_history_404_when_account_not_found():
    from main import app
    from db.postgres import get_db as real_get_db

    async def override_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = None
        yield mock_db

    app.dependency_overrides[real_get_db] = override_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/accounts/999/history/sync")

    app.dependency_overrides = {}
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sync_history_503_when_mt5_unavailable():
    from main import app
    from db.postgres import get_db as real_get_db

    mock_account = _mock_account()

    async def override_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_account
        yield mock_db

    app.dependency_overrides[real_get_db] = override_db

    with patch("api.routes.accounts.HistoryService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.sync_to_db = AsyncMock(side_effect=RuntimeError("MT5 not installed"))
        mock_svc_cls.return_value = mock_svc

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/accounts/1/history/sync")

    app.dependency_overrides = {}
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_sync_history_502_on_connection_error():
    from main import app
    from db.postgres import get_db as real_get_db

    mock_account = _mock_account()

    async def override_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_account
        yield mock_db

    app.dependency_overrides[real_get_db] = override_db

    with patch("api.routes.accounts.HistoryService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.sync_to_db = AsyncMock(side_effect=ConnectionError("MT5 broker unreachable"))
        mock_svc_cls.return_value = mock_svc

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/accounts/1/history/sync")

    app.dependency_overrides = {}
    assert resp.status_code == 502
