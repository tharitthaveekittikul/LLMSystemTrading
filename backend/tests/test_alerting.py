import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.alerting import send_alert


@pytest.mark.asyncio
async def test_send_alert_skips_when_not_configured():
    """send_alert does nothing when token/chat_id are empty."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = ""
        mock_cfg.telegram_chat_id = ""

        with patch("services.alerting.httpx.AsyncClient") as mock_cls:
            await send_alert("test message")
            mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_alert_skips_when_chat_id_missing():
    """send_alert skips when token is set but chat_id is empty."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = "some-token"
        mock_cfg.telegram_chat_id = ""

        with patch("services.alerting.httpx.AsyncClient") as mock_cls:
            await send_alert("test message")
            mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_alert_posts_to_telegram():
    """send_alert calls the Telegram API when both token and chat_id are set."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = "test-token"
        mock_cfg.telegram_chat_id = "123456"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("services.alerting.httpx.AsyncClient", return_value=mock_client):
            await send_alert("hello world")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "test-token" in call_args.args[0]   # URL contains token
        assert "hello world" in str(call_args.kwargs)  # message in payload


@pytest.mark.asyncio
async def test_send_alert_silently_handles_network_error():
    """Network failure never raises from send_alert."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = "token"
        mock_cfg.telegram_chat_id = "123"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with patch("services.alerting.httpx.AsyncClient", return_value=mock_client):
            # Must not raise
            await send_alert("critical error")
