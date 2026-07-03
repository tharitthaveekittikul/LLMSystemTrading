"""Tests for MT5Bridge's warm-session connection reuse (Part B).

Root cause under test: every `async with MT5Bridge(creds)` previously paid a
full mt5.initialize()/mt5.shutdown() handshake, even for calls seconds apart
on the same account — 808 connect/disconnect cycles in a 6h12m log window.
The fix keeps one MT5 login warm across consecutive uses, swapping only when
a different account is requested, and reaps it after an idle timeout.
"""
import asyncio

import pytest

import mt5.bridge as bridge_module
from mt5.bridge import AccountCredentials, MT5Bridge, SessionBusyError


def _creds(login: int, server: str = "srv") -> AccountCredentials:
    return AccountCredentials(login=login, password="pw", server=server)


@pytest.fixture(autouse=True)
async def _reset_warm_session_state():
    """Warm-session state is module-global — isolate each test from the last."""
    bridge_module._live = None
    if bridge_module._reaper_task is not None:
        bridge_module._reaper_task.cancel()
        bridge_module._reaper_task = None
    yield
    if bridge_module._reaper_task is not None:
        bridge_module._reaper_task.cancel()
        bridge_module._reaper_task = None
    bridge_module._live = None


@pytest.fixture
def mock_mt5(monkeypatch):
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.initialize.return_value = True
    mock.shutdown.return_value = None
    monkeypatch.setattr(bridge_module, "MT5_AVAILABLE", True)
    monkeypatch.setattr(bridge_module, "mt5", mock)
    return mock


@pytest.mark.asyncio
async def test_second_entry_for_same_account_reuses_session_no_reinit(mock_mt5):
    creds = _creds(1)
    async with MT5Bridge(creds):
        pass
    async with MT5Bridge(creds):
        pass

    assert mock_mt5.initialize.call_count == 1
    assert mock_mt5.shutdown.call_count == 0  # __aexit__ must NOT disconnect


@pytest.mark.asyncio
async def test_different_account_triggers_swap(mock_mt5):
    async with MT5Bridge(_creds(1)):
        pass
    async with MT5Bridge(_creds(2)):
        pass

    assert mock_mt5.initialize.call_count == 2
    assert mock_mt5.shutdown.call_count == 1  # old session torn down before the new login


@pytest.mark.asyncio
async def test_pinned_session_blocks_other_account(mock_mt5):
    await MT5Bridge.pin_session(_creds(1))

    with pytest.raises(SessionBusyError):
        async with MT5Bridge(_creds(2)):
            pass

    await MT5Bridge.unpin_session()


@pytest.mark.asyncio
async def test_unpin_allows_swap_afterwards(mock_mt5):
    await MT5Bridge.pin_session(_creds(1))
    await MT5Bridge.unpin_session()

    async with MT5Bridge(_creds(2)):
        pass

    assert mock_mt5.shutdown.call_count == 1
    assert mock_mt5.initialize.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_forces_reconnect_on_next_entry(mock_mt5):
    creds = _creds(1)
    async with MT5Bridge(creds):
        pass
    await MT5Bridge.invalidate()

    async with MT5Bridge(creds):
        pass

    assert mock_mt5.initialize.call_count == 2


@pytest.mark.asyncio
async def test_force_shutdown_tears_down_and_clears_state(mock_mt5):
    async with MT5Bridge(_creds(1)):
        pass

    await MT5Bridge.force_shutdown()

    assert mock_mt5.shutdown.call_count == 1
    assert bridge_module._live is None


@pytest.mark.asyncio
async def test_idle_session_is_reaped(mock_mt5, monkeypatch):
    monkeypatch.setattr(bridge_module, "_IDLE_TIMEOUT", 0.0)
    monkeypatch.setattr(bridge_module, "_REAPER_INTERVAL", 0.01)

    async with MT5Bridge(_creds(1)):
        pass

    # Reaper checks every _REAPER_INTERVAL and shuts down once idle > _IDLE_TIMEOUT (0s).
    for _ in range(50):
        await asyncio.sleep(0.01)
        if bridge_module._live is None:
            break

    assert bridge_module._live is None
    assert mock_mt5.shutdown.call_count == 1


@pytest.mark.asyncio
async def test_connect_failure_releases_lock_and_raises(mock_mt5):
    mock_mt5.initialize.return_value = False
    mock_mt5.last_error.return_value = (-1, "boom")

    with pytest.raises(ConnectionError):
        async with MT5Bridge(_creds(1)):
            pass

    # Lock must be released on failure — a subsequent entry must not hang,
    # and should succeed once the broker connection recovers.
    mock_mt5.initialize.return_value = True
    async with asyncio.timeout(1):
        async with MT5Bridge(_creds(1)):
            pass
