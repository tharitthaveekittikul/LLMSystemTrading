"""Test configuration — patches SQLAlchemy engine to use NullPool and cleans up
test artifacts before and after the full test session.

NullPool disables connection pooling so asyncpg connections are closed
synchronously at the end of each request. This prevents background
cancel-callbacks from firing on a closed event loop when multiple test
modules each spin up the app lifespan in sequence.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine
import db.postgres as postgres_module
from core.config import settings

# ── Known test-data markers ───────────────────────────────────────────────────
_TEST_STRATEGY_NAMES = ["Test M15"]
_TEST_ACCOUNT_BROKERS = ["TestBroker"]


@pytest.fixture(autouse=True, scope="session")
def patch_db_engine():
    """Replace the pooled engine with a NullPool engine for all tests."""
    test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    original_engine = postgres_module.engine
    postgres_module.engine = test_engine
    postgres_module.AsyncSessionLocal = __import__(
        "sqlalchemy.ext.asyncio", fromlist=["async_sessionmaker"]
    ).async_sessionmaker(test_engine, expire_on_commit=False)
    yield
    postgres_module.engine = original_engine


@pytest_asyncio.fixture(autouse=True, scope="session", loop_scope="session")
async def cleanup_test_data(patch_db_engine):  # noqa: ARG001 — used for ordering only
    """Delete known test artifacts before and after the full test session.

    Running before the session handles leftovers from a previously interrupted
    run. Running after ensures a clean state after a normal run.
    """
    await _purge_test_artifacts()
    yield
    await _purge_test_artifacts()


async def _purge_test_artifacts() -> None:
    """Remove rows that tests are known to insert into PostgreSQL."""
    try:
        async with postgres_module.AsyncSessionLocal() as db:
            # Strategies created by test_strategy_routes
            for name in _TEST_STRATEGY_NAMES:
                await db.execute(
                    text("DELETE FROM strategies WHERE name = :n"), {"n": name}
                )
            # Accounts created by test_account_stats / test_equity_history
            # (cascade deletes related trades, journal, pipeline_runs, etc.)
            for broker in _TEST_ACCOUNT_BROKERS:
                await db.execute(
                    text("DELETE FROM accounts WHERE broker = :b"), {"b": broker}
                )
            await db.commit()
    except Exception:
        pass  # DB not reachable in offline CI — that is fine
