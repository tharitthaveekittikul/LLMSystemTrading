from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_retry_run_returns_404_for_missing_run(client):
    """POST /api/v1/pipeline/runs/{id}/retry on a nonexistent run returns 404.

    Uses an id far outside any real sequence so this can never collide with
    a real pipeline run in a shared (non-isolated) test database.
    """
    response = await client.post("/api/v1/pipeline/runs/999999999/retry")
    assert response.status_code == 404


async def test_retry_run_dispatches_to_analyze_and_trade(client):
    """A retryable run triggers AITradingService.analyze_and_trade with its
    account/symbol/timeframe. AITradingService is mocked so this never touches
    a real account, MT5, or an LLM provider — this DB is shared with live
    trading data, so no test here may execute the real pipeline.
    """
    from datetime import UTC, datetime

    from ai.orchestrator import TradingSignal
    from db.models import PipelineRun
    from db.postgres import AsyncSessionLocal
    from services.ai_trading import AnalysisResult

    unique_login = int(datetime.now(UTC).strftime("%H%M%S%f")) % 2_000_000_000
    create_resp = await client.post("/api/v1/accounts", json={
        "name": "Retry Test",
        "broker": "TestBroker",
        "login": unique_login,
        "password": "pass",
        "server": "test.server.com",
    })
    if create_resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = create_resp.json()["id"]

    run_id = None
    try:
        async with AsyncSessionLocal() as db:
            run = PipelineRun(
                account_id=account_id,
                symbol="EURUSD",
                timeframe="M15",
                task_type="signal",
                status="failed",
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        fake_signal = TradingSignal(
            action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0,
            confidence=0.5, rationale="test", timeframe="M15",
        )
        fake_result = AnalysisResult(
            signal=fake_signal, order_placed=False, ticket=None, journal_id=1,
        )

        with patch(
            "services.ai_trading.AITradingService.analyze_and_trade",
            new_callable=AsyncMock, return_value=fake_result,
        ) as mock_analyze:
            response = await client.post(f"/api/v1/pipeline/runs/{run_id}/retry")

        assert response.status_code == 200
        assert response.json()["action"] == "HOLD"
        mock_analyze.assert_awaited_once()
        kwargs = mock_analyze.await_args.kwargs
        assert kwargs["account_id"] == account_id
        assert kwargs["symbol"] == "EURUSD"
        assert kwargs["timeframe"] == "M15"
        assert kwargs["strategy_id"] is None
    finally:
        if run_id is not None:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                await db.execute(delete(PipelineRun).where(PipelineRun.id == run_id))
                await db.commit()
        await client.delete(f"/api/v1/accounts/{account_id}")


async def test_retry_run_rejects_maintenance_task_type(client):
    """Only task_type='signal' runs can be retried."""
    from datetime import UTC, datetime

    from db.models import PipelineRun
    from db.postgres import AsyncSessionLocal

    unique_login = int(datetime.now(UTC).strftime("%H%M%S%f")) % 2_000_000_000
    create_resp = await client.post("/api/v1/accounts", json={
        "name": "Retry Maintenance Test",
        "broker": "TestBroker",
        "login": unique_login,
        "password": "pass",
        "server": "test.server.com",
    })
    if create_resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = create_resp.json()["id"]

    run_id = None
    try:
        async with AsyncSessionLocal() as db:
            run = PipelineRun(
                account_id=account_id,
                symbol="EURUSD",
                timeframe="M15",
                task_type="maintenance",
                status="failed",
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        response = await client.post(f"/api/v1/pipeline/runs/{run_id}/retry")
        assert response.status_code == 400
    finally:
        if run_id is not None:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                await db.execute(delete(PipelineRun).where(PipelineRun.id == run_id))
                await db.commit()
        await client.delete(f"/api/v1/accounts/{account_id}")
