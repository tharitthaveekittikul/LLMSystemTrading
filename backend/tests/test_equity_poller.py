import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_poll_account_calls_insert_and_broadcast():
    """_poll_account writes to QuestDB and broadcasts equity_update."""
    from services.equity_poller import _poll_account

    mock_account = {
        "id": 1,
        "login": 12345,
        "server": "test.server",
        "password_encrypted": "dummy",
        "mt5_path": "",
    }

    mock_info = {
        "balance": 10000.0, "equity": 10050.0, "margin": 200.0,
        "margin_free": 9800.0, "margin_level": 5025.0, "currency": "USD",
    }

    insert_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    with patch("services.equity_poller.decrypt", return_value="plainpass"), \
         patch("services.equity_poller.MT5Bridge") as mock_bridge_cls:
        mock_bridge = AsyncMock()
        mock_bridge.get_account_info = AsyncMock(return_value=mock_info)
        mock_bridge_cls.return_value.__aenter__ = AsyncMock(return_value=mock_bridge)
        mock_bridge_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_account(mock_account, insert_mock, broadcast_mock)

    insert_mock.assert_called_once_with(
        account_id=1, equity=10050.0, balance=10000.0, margin=200.0
    )
    broadcast_mock.assert_called_once()
    call_args = broadcast_mock.call_args
    assert call_args[0][0] == 1
    assert call_args[0][1] == "equity_update"
    data = call_args[0][2]
    assert data["equity"] == 10050.0
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_poll_account_swallows_mt5_error():
    """_poll_account does not raise even when MT5 fails."""
    from services.equity_poller import _poll_account

    mock_account = {
        "id": 2,
        "login": 99999,
        "server": "test.server",
        "password_encrypted": "dummy",
        "mt5_path": "",
    }

    insert_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    with patch("services.equity_poller.decrypt", return_value="plainpass"), \
         patch("services.equity_poller.MT5Bridge") as mock_bridge_cls:
        mock_bridge_cls.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("MT5 down"))
        mock_bridge_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_account(mock_account, insert_mock, broadcast_mock)

    insert_mock.assert_not_called()
    broadcast_mock.assert_not_called()


async def _noop(*args, **kwargs):
    pass


@pytest.mark.asyncio
async def test_poll_account_activates_kill_switch_on_drawdown(monkeypatch):
    """Drawdown >= max_drawdown_percent must activate the kill switch."""
    import services.kill_switch as ks

    # Reset kill switch state and patch DB + WS side effects
    monkeypatch.setattr(ks, "_active", False)
    monkeypatch.setattr(ks, "_persist", lambda *a, **k: _noop())
    monkeypatch.setattr(ks, "_broadcast_kill_switch", lambda *a, **k: _noop())

    mock_info = {
        "equity": 8000.0, "balance": 10000.0,
        "margin": 0.0, "margin_free": 8000.0,
        "margin_level": 0.0, "currency": "USD",
    }

    from unittest.mock import AsyncMock, patch

    inserted = []
    broadcasts = []

    from services.equity_poller import _poll_account
    with patch("services.equity_poller.settings") as mock_cfg:
        mock_cfg.mt5_path = ""
        mock_cfg.max_drawdown_percent = 10.0

        with patch("services.equity_poller.MT5Bridge") as mock_bridge_cls:
            mock_bridge = AsyncMock()
            mock_bridge.get_account_info.return_value = mock_info
            mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

            account = {"id": 99, "login": 1, "password_encrypted": "x", "server": "srv", "mt5_path": ""}
            with patch("services.equity_poller.decrypt", return_value="pass"):
                await _poll_account(
                    account,
                    lambda **k: inserted.append(k),
                    lambda *a, **k: broadcasts.append(k)
                )

    assert ks.is_active() is True
    # Clean up kill switch state
    await ks.deactivate()
