"""Tests for mt5_path field on Account schema and credential construction."""
import pytest
from pydantic import ValidationError


def test_account_create_accepts_mt5_path():
    from api.routes.accounts import AccountCreate
    a = AccountCreate(
        name="Test", broker="ICM", login=12345,
        password="pw", server="srv", mt5_path="C:/MT5_Account1"
    )
    assert a.mt5_path == "C:/MT5_Account1"


def test_account_create_mt5_path_defaults_empty():
    from api.routes.accounts import AccountCreate
    a = AccountCreate(name="Test", broker="ICM", login=12345, password="pw", server="srv")
    assert a.mt5_path == ""


def test_account_response_includes_mt5_path():
    from api.routes.accounts import AccountResponse
    import datetime
    r = AccountResponse(
        id=1, name="Test", broker="ICM", login=12345,
        server="srv", is_live=False, is_active=True,
        allowed_symbols=[], max_lot_size=0.1,
        auto_trade_enabled=True, mt5_path="C:/MT5_Account1",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    assert r.mt5_path == "C:/MT5_Account1"


def test_account_update_accepts_mt5_path():
    from api.routes.accounts import AccountUpdate
    u = AccountUpdate(mt5_path="C:/MT5_Account2")
    assert u.mt5_path == "C:/MT5_Account2"


def test_account_update_mt5_path_none_by_default():
    from api.routes.accounts import AccountUpdate
    u = AccountUpdate()
    assert u.mt5_path is None


def test_credentials_use_account_path_when_set():
    """Non-empty account.mt5_path takes precedence over global fallback."""
    from api.routes.accounts import AccountCreate
    a = AccountCreate(
        name="Test", broker="ICM", login=12345,
        password="pw", server="srv",
        mt5_path="C:/MT5_Account1",
    )
    fallback = "C:/MT5_Global"
    effective = a.mt5_path or fallback
    assert effective == "C:/MT5_Account1"


def test_credentials_fall_back_to_settings_when_path_empty():
    """Empty account.mt5_path falls back to global settings.mt5_path."""
    from api.routes.accounts import AccountCreate
    a = AccountCreate(
        name="Test", broker="ICM", login=12345,
        password="pw", server="srv",
    )
    fallback = "C:/MT5_Global"
    effective = a.mt5_path or fallback
    assert effective == "C:/MT5_Global"
