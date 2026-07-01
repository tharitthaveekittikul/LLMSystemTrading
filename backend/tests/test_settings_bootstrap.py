"""Tests for services/settings_bootstrap.ensure_global_settings_row.

Uses a mocked AsyncSession (matches the pattern in test_ai_trading.py) rather
than a real DB connection — this table holds a live singleton row shared by
the running dev backend, so we must not mutate it from the test suite.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import GlobalSettings as GlobalSettingsModel
from services.settings_bootstrap import ensure_global_settings_row


@pytest.mark.asyncio
async def test_creates_row_seeded_from_settings_when_absent():
    """Fresh deploy: no row exists yet → one is created and persisted,
    seeded from the current in-memory settings (config default / .env)."""
    mock_db = AsyncMock()
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = _exec_result

    # Pin news_enabled explicitly rather than relying on the local .env —
    # this test verifies the seeding wiring, not the ambient config value.
    with patch("services.settings_bootstrap.settings") as mock_settings:
        mock_settings.news_enabled = True
        mock_settings.maintenance_interval_minutes = 60
        mock_settings.maintenance_task_enabled = True
        mock_settings.llm_confidence_threshold = 0.70
        mock_settings.enable_agent_pipeline = False
        mock_settings.enable_indicator_agent = True
        mock_settings.enable_pattern_agent = True
        mock_settings.enable_trend_agent = True

        row = await ensure_global_settings_row(mock_db)

    assert row.news_enabled is True
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_never_overwrites_an_existing_row():
    """Existing deploy: a row already exists (news_enabled explicitly False)
    → it must be returned untouched, no add/commit performed."""
    existing = GlobalSettingsModel(id=1, news_enabled=False)
    mock_db = AsyncMock()
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = _exec_result

    row = await ensure_global_settings_row(mock_db)

    assert row is existing
    assert row.news_enabled is False
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_never_overwrites_an_existing_row_when_explicitly_true():
    """Symmetric case — an explicit True must also survive untouched."""
    existing = GlobalSettingsModel(id=1, news_enabled=True)
    mock_db = AsyncMock()
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = _exec_result

    row = await ensure_global_settings_row(mock_db)

    assert row is existing
    assert row.news_enabled is True
    mock_db.add.assert_not_called()
