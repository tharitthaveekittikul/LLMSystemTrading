"""Tests for plan 04: research-loop trust score + confidence gate modulation.

Covers the deterministic (non-LLM) trust-score math in services/research_loop.py
and confirms the confidence gate produces different outcomes for the same raw
signal confidence depending on the symbol's trust score — the core behavior
this plan adds (replacing the dead blocked_symbols/suggested_params fields).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.research_loop import (
    TRUST_MAX_THRESHOLD,
    TRUST_MIN_THRESHOLD,
    _trust_score_from_stats,
    _wilson_lower_bound,
    compute_effective_threshold,
    compute_symbol_trust_scores,
    effective_confidence_threshold,
)

# ── _wilson_lower_bound ─────────────────────────────────────────────────────

def test_wilson_lower_bound_no_trades_is_neutral():
    assert _wilson_lower_bound(0, 0) == 0.5


def test_wilson_lower_bound_increases_with_more_wins():
    low = _wilson_lower_bound(wins=5, n=20)
    high = _wilson_lower_bound(wins=18, n=20)
    assert high > low


def test_wilson_lower_bound_stays_in_unit_interval():
    assert 0.0 <= _wilson_lower_bound(wins=100, n=100) <= 1.0
    assert 0.0 <= _wilson_lower_bound(wins=0, n=100) <= 1.0


# ── _trust_score_from_stats ──────────────────────────────────────────────────

def test_trust_score_neutral_when_no_trades():
    assert _trust_score_from_stats(wins=0, n=0) == 0.5


def test_trust_score_stays_near_neutral_for_small_sample():
    """A handful of trades (well under min_sample) shouldn't swing the score
    far from 0.5 in either direction — even a perfect win rate over 3 trades
    is not enough evidence, and the conservative Wilson bound reflects that."""
    score = _trust_score_from_stats(wins=3, n=3, min_sample=20)
    assert 0.4 <= score <= 0.6


def test_trust_score_approaches_wilson_bound_at_full_sample():
    wins, n = 18, 20
    score = _trust_score_from_stats(wins=wins, n=n, min_sample=20)
    assert score == round(_wilson_lower_bound(wins, n), 3)


def test_trust_score_below_neutral_for_poor_performer_with_enough_samples():
    score = _trust_score_from_stats(wins=5, n=30, min_sample=20)
    assert score < 0.5


# ── compute_effective_threshold ──────────────────────────────────────────────

def test_effective_threshold_equals_base_at_neutral_trust():
    assert compute_effective_threshold(0.70, 0.5) == pytest.approx(0.70)


def test_effective_threshold_lower_for_trusted_symbol():
    trusted = compute_effective_threshold(0.70, trust_score=0.9)
    assert trusted < 0.70


def test_effective_threshold_higher_for_distrusted_symbol():
    distrusted = compute_effective_threshold(0.70, trust_score=0.1)
    assert distrusted > 0.70


def test_effective_threshold_clamped_to_bounds():
    # Extreme trust score with high sensitivity should still clamp
    assert compute_effective_threshold(0.70, trust_score=1.0, sensitivity=5.0) == TRUST_MIN_THRESHOLD
    assert compute_effective_threshold(0.70, trust_score=0.0, sensitivity=5.0) == TRUST_MAX_THRESHOLD


def test_same_confidence_different_trust_scores_flip_gate_outcome():
    """The plan's acceptance criterion: identical raw signal confidence, two
    different trust scores, two different gate outcomes."""
    base_threshold = 0.70
    signal_confidence = 0.60

    trusted_threshold = compute_effective_threshold(base_threshold, trust_score=0.9)
    distrusted_threshold = compute_effective_threshold(base_threshold, trust_score=0.1)

    trusted_passes = signal_confidence >= trusted_threshold
    distrusted_passes = signal_confidence >= distrusted_threshold

    assert trusted_passes is True
    assert distrusted_passes is False
    assert trusted_passes != distrusted_passes


def test_effective_confidence_threshold_reads_persisted_score(monkeypatch):
    monkeypatch.setattr(
        "services.research_loop.read_config",
        lambda: {"symbol_trust_scores": {"EURUSD": 0.9}},
    )
    threshold = effective_confidence_threshold("EURUSD", 0.70)
    assert threshold == compute_effective_threshold(0.70, 0.9)


def test_effective_confidence_threshold_defaults_neutral_for_unknown_symbol(monkeypatch):
    monkeypatch.setattr(
        "services.research_loop.read_config",
        lambda: {"symbol_trust_scores": {"EURUSD": 0.9}},
    )
    threshold = effective_confidence_threshold("XAUUSD", 0.70)
    assert threshold == pytest.approx(0.70)


# ── compute_symbol_trust_scores (DB query, mocked session) ──────────────────

@pytest.mark.asyncio
async def test_compute_symbol_trust_scores_queries_db_and_scores_each_symbol():
    rows = [
        SimpleNamespace(symbol="EURUSD", n=25, wins=20),
        SimpleNamespace(symbol="XAUUSD", n=25, wins=5),
        SimpleNamespace(symbol="GBPUSD", n=2, wins=2),
    ]
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    scores = await compute_symbol_trust_scores(mock_db, account_id=1)

    assert scores["EURUSD"] > 0.5  # good win rate, enough samples
    assert scores["XAUUSD"] < 0.5  # poor win rate, enough samples
    assert 0.4 <= scores["GBPUSD"] <= 0.6  # perfect win rate but tiny sample — stays near neutral
