"""Test configuration — patches SQLAlchemy engine to use NullPool.

NullPool disables connection pooling so asyncpg connections are closed
synchronously at the end of each request. This prevents background
cancel-callbacks from firing on a closed event loop when multiple test
modules each spin up the app lifespan in sequence.
"""
import pytest
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine
import db.postgres as postgres_module
from core.config import settings


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
