import pytest

import services.kill_switch as ks


@pytest.mark.asyncio
async def test_kill_switch_default_inactive():
    assert ks.is_active() is False


@pytest.mark.asyncio
async def test_kill_switch_activate_deactivate(monkeypatch):
    # Patch DB + WS to avoid side effects in unit tests
    monkeypatch.setattr(ks, "_persist", lambda *a, **k: _noop())
    monkeypatch.setattr(ks, "_broadcast_kill_switch", lambda *a, **k: _noop())

    await ks.activate("test reason")
    assert ks.is_active() is True

    await ks.deactivate()
    assert ks.is_active() is False


async def _noop():
    pass
