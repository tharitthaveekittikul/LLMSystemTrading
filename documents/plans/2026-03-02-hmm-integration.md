# HMM Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate a Hidden Markov Model for market regime detection that filters live trading signals and retrains weekly via APScheduler.

**Architecture:** Four new files (`hmm_features.py`, `hmm_service.py`, `hmm_retrain.py`, `hmm_strategy.py`) and five modified files (`base_strategy.py`, `orchestrator.py`, `ai_trading.py`, `scheduler.py`, `models.py`). `HMMService` is cached per symbol inside `AITradingService`. Regime detection runs as Step 5.5 in `_run_pipeline()`; the regime filter produces a new `TradingSignal` (no mutation) before the journal is saved. All four bugs from the audit are fixed in this plan.

**Tech Stack:** `hmmlearn >= 0.3.2`, numpy (already present), APScheduler CronTrigger (already present), SQLAlchemy Mapped models, pickle for model persistence (standard for hmmlearn/scikit-learn — models are internal, never deserialized from user input).

---

## Audit Bug Fixes Applied

| # | Bug | Where Fixed |
|---|-----|-------------|
| 1 | `REGIME_LABELS` module-level global — cross-symbol contamination | Task 3 — `self.regime_labels` instance variable |
| 2 | `predict()` standardises with window stats, not training stats | Task 3 — `self._train_mean` / `self._train_std` saved and reused |
| 3 | `DetachedInstanceError` — account attrs accessed outside DB session | Task 7 — all attrs read inside session, passed as plain dict |
| 4 | Async lazy-load of `AccountStrategy.strategy` raises `MissingGreenlet` | Task 7 — `selectinload` used in the query |

---

## Task 1: Add `hmmlearn` dependency

**Files:**
- Modify: `backend/pyproject.toml`

**Step 1: Add to dependencies list**

In `pyproject.toml`, add after `"pandas>=3.0.1",`:

```toml
"hmmlearn>=0.3.2",
```

**Step 2: Install**

```bash
cd backend && uv add hmmlearn
```

Expected: resolves and installs `hmmlearn 0.3.x`, updates `uv.lock`.

---

## Task 2: Create `hmm_features.py` and its tests

**Files:**
- Create: `backend/services/hmm_features.py`
- Create: `backend/tests/test_hmm_features.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_hmm_features.py
import numpy as np
import pytest

from services.hmm_features import extract_features


@pytest.fixture
def sample_candles_200():
    """200 synthetic OHLCV candles with realistic FX values."""
    rng = np.random.default_rng(42)
    closes = 1.0850 + np.cumsum(rng.normal(0, 0.0005, 200))
    result = []
    for i, c in enumerate(closes):
        h  = c + abs(rng.normal(0, 0.0002))
        lo = c - abs(rng.normal(0, 0.0002))
        result.append({
            "open":        float(closes[i - 1] if i > 0 else c),
            "high":        float(h),
            "low":         float(lo),
            "close":       float(c),
            "tick_volume": float(rng.integers(500, 5000)),
        })
    return result


def test_extract_features_shape(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert X.shape == (200, 4)


def test_extract_features_no_nan_or_inf(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert not np.any(np.isnan(X))
    assert not np.any(np.isinf(X))


def test_extract_features_column_ranges(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert abs(X[:, 0]).max() < 0.1      # log_return — small for FX
    assert (X[:, 1] >= 0).all()           # realized_vol — non-negative
    assert (X[:, 2] > 0).all()            # atr_norm — small positive ratio
    assert X[:, 2].max() < 0.1
    assert (X[:, 3] > 0).all()            # volume_ratio — positive
```

**Step 2: Run to confirm failure**

```bash
cd backend && uv run pytest tests/test_hmm_features.py -v
```

Expected: `ImportError: No module named 'services.hmm_features'`

**Step 3: Create `hmm_features.py`**

```python
# backend/services/hmm_features.py
"""Feature extraction for HMM training and inference."""
import numpy as np


def extract_features(candles: list[dict]) -> np.ndarray:
    """
    Returns shape (n_samples, 4) array:
      col 0: log_return
      col 1: realized_vol  (14-bar rolling std of log_return)
      col 2: atr_norm      (ATR14 / close)
      col 3: volume_ratio  (volume / rolling_mean_vol_20)
    """
    closes  = np.array([c["close"]       for c in candles], dtype=float)
    highs   = np.array([c["high"]        for c in candles], dtype=float)
    lows    = np.array([c["low"]         for c in candles], dtype=float)
    volumes = np.array([c["tick_volume"] for c in candles], dtype=float)

    log_ret = np.diff(np.log(closes), prepend=np.log(closes[0]))

    # Realized vol: rolling 14-bar std
    rvol = np.array([
        log_ret[max(0, i - 13):i + 1].std() if i >= 13 else log_ret[:i + 1].std()
        for i in range(len(log_ret))
    ])

    # True range using explicit shifted close (avoids np.roll index-0 edge case)
    prev_closes = np.empty_like(closes)
    prev_closes[0] = closes[0]
    prev_closes[1:] = closes[:-1]
    tr = np.maximum(
        highs - lows,
        np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)),
    )
    atr      = np.array([tr[max(0, i - 13):i + 1].mean() for i in range(len(tr))])
    atr_norm = atr / closes

    # Volume ratio
    vol_mean  = np.array([volumes[max(0, i - 19):i + 1].mean() for i in range(len(volumes))])
    vol_ratio = volumes / np.where(vol_mean > 0, vol_mean, 1.0)

    return np.column_stack([log_ret, rvol, atr_norm, vol_ratio])
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_hmm_features.py -v
```

Expected: 3 tests PASS.

---

## Task 3: Create `hmm_service.py` and its tests

**Files:**
- Create: `backend/services/hmm_service.py`
- Create: `backend/tests/test_hmm_service.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_hmm_service.py
import numpy as np
import pytest

from services.hmm_service import HMMService

_VALID_REGIMES = {"trending_bullish", "trending_bearish", "ranging", "high_volatility"}


@pytest.fixture
def sample_candles_200():
    rng = np.random.default_rng(42)
    closes = 1.0850 + np.cumsum(rng.normal(0, 0.0005, 200))
    result = []
    for i, c in enumerate(closes):
        h  = c + abs(rng.normal(0, 0.0002))
        lo = c - abs(rng.normal(0, 0.0002))
        result.append({
            "open":        float(closes[i - 1] if i > 0 else c),
            "high":        float(h),
            "low":         float(lo),
            "close":       float(c),
            "tick_volume": float(rng.integers(500, 5000)),
        })
    return result


def test_train_predict_returns_valid_regime(tmp_path, sample_candles_200):
    svc = HMMService("EURUSD", "D1")
    svc._model_path = str(tmp_path / "model.pkl")
    svc.train(sample_candles_200)
    result = svc.predict(sample_candles_200[-50:])
    assert result["regime"] in _VALID_REGIMES
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["state"] in {0, 1, 2, 3}


def test_predict_without_model_returns_unknown():
    svc = HMMService("EURUSD_NOMODEL", "D1")
    svc._model_path = "/nonexistent/path.pkl"
    svc.model = None
    result = svc.predict([])
    assert result["regime"] == "unknown"
    assert result["confidence"] == 0.0


def test_persist_and_reload(tmp_path, sample_candles_200):
    path = str(tmp_path / "model.pkl")
    svc1 = HMMService("USDJPY", "D1")
    svc1._model_path = path
    svc1.train(sample_candles_200)

    svc2 = HMMService("USDJPY", "D1")
    svc2._model_path = path
    svc2._load_model()
    assert svc2.model is not None
    assert svc2._train_mean is not None
    assert svc2._train_std is not None


def test_multiple_symbols_have_independent_labels(tmp_path, sample_candles_200):
    """Bug fix #1: no module-level global — each instance has its own labels dict."""
    svc_eur = HMMService("EURUSD", "D1")
    svc_eur._model_path = str(tmp_path / "eur.pkl")
    svc_eur.train(sample_candles_200)

    svc_xau = HMMService("XAUUSD", "D1")
    svc_xau._model_path = str(tmp_path / "xau.pkl")
    svc_xau.train(sample_candles_200)

    assert svc_eur.regime_labels is not svc_xau.regime_labels


def test_predict_uses_training_stats_not_window_stats(tmp_path, sample_candles_200):
    """Bug fix #2: training mean/std must be stable across predict() calls."""
    svc = HMMService("EURUSD", "D1")
    svc._model_path = str(tmp_path / "model.pkl")
    svc.train(sample_candles_200)

    mean_before = svc._train_mean.copy()
    std_before  = svc._train_std.copy()
    svc.predict(sample_candles_200[-50:])
    np.testing.assert_array_equal(svc._train_mean, mean_before)
    np.testing.assert_array_equal(svc._train_std,  std_before)


def test_train_raises_on_too_few_candles(tmp_path):
    svc = HMMService("EURUSD", "D1")
    svc._model_path = str(tmp_path / "model.pkl")
    with pytest.raises(ValueError, match="at least 50"):
        svc.train([
            {"close": 1.0, "high": 1.01, "low": 0.99, "tick_volume": 1000}
        ] * 10)
```

**Step 2: Run to confirm failure**

```bash
cd backend && uv run pytest tests/test_hmm_service.py -v
```

Expected: `ImportError: No module named 'services.hmm_service'`

**Step 3: Create `hmm_service.py`**

```python
# backend/services/hmm_service.py
"""HMM Market Regime Service."""
import logging
import os
import pickle
from datetime import UTC, datetime

import numpy as np
from hmmlearn import hmm

from services.hmm_features import extract_features

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "hmm_models")
N_STATES   = 4

_DEFAULT_REGIME_LABELS: dict[int, str] = {
    0: "trending_bullish",
    1: "trending_bearish",
    2: "ranging",
    3: "high_volatility",
}


class HMMService:
    def __init__(self, symbol: str, timeframe: str = "D1"):
        self.symbol    = symbol
        self.timeframe = timeframe
        self.model: hmm.GaussianHMM | None = None
        # Bug Fix #1: instance-level labels dict — never a module global
        self.regime_labels: dict[int, str] = dict(_DEFAULT_REGIME_LABELS)
        # Bug Fix #2: training-time scaler params saved alongside model
        self._train_mean: np.ndarray | None = None
        self._train_std:  np.ndarray | None = None
        self._model_path  = os.path.join(MODEL_DIR, f"hmm_{symbol}_{timeframe}.pkl")
        os.makedirs(MODEL_DIR, exist_ok=True)
        self._load_model()

    # ── Training ─────────────────────────────────────────────────────────────

    def train(self, candles: list[dict]) -> None:
        """Train on historical candles (minimum 50 required)."""
        if len(candles) < 50:
            raise ValueError("Need at least 50 candles to train HMM")

        X = extract_features(candles)
        self._train_mean = X.mean(axis=0)
        self._train_std  = X.std(axis=0) + 1e-8
        X_scaled = (X - self._train_mean) / self._train_std

        model = hmm.GaussianHMM(
            n_components=N_STATES,
            covariance_type="diag",
            n_iter=200,
            random_state=42,
        )
        model.fit(X_scaled)
        self.model = model
        self._label_states()
        self._save_model()
        logger.info(
            "HMM trained | symbol=%s timeframe=%s candles=%d score=%.4f",
            self.symbol, self.timeframe, len(candles), model.score(X_scaled),
        )

    def _label_states(self) -> None:
        """Auto-label states by mean log_return. Writes to self.regime_labels only."""
        if self.model is None:
            return
        means  = self.model.means_[:, 0]
        ranked = np.argsort(means)
        self.regime_labels = {
            int(ranked[0]): "trending_bearish",
            int(ranked[1]): "ranging",
            int(ranked[2]): "ranging",
            int(ranked[3]): "trending_bullish",
        }
        vols       = self.model.means_[:, 1]
        mid_states = [int(ranked[1]), int(ranked[2])]
        high_vol   = mid_states[int(np.argmax([vols[s] for s in mid_states]))]
        self.regime_labels[high_vol] = "high_volatility"

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, candles: list[dict]) -> dict:
        """Predict current regime. Returns {"state", "regime", "confidence"}."""
        if self.model is None or self._train_mean is None:
            return {"state": -1, "regime": "unknown", "confidence": 0.0}

        window = candles[-max(50, len(candles)):]
        if len(window) < 2:
            return {"state": -1, "regime": "unknown", "confidence": 0.0}

        X = extract_features(window)
        # Bug Fix #2: use training-time stats for consistent standardisation
        X_scaled      = (X - self._train_mean) / self._train_std
        _, state_seq  = self.model.decode(X_scaled, algorithm="viterbi")
        current_state = int(state_seq[-1])
        posteriors    = self.model.predict_proba(X_scaled)
        confidence    = float(posteriors[-1, current_state])

        return {
            "state":      current_state,
            "regime":     self.regime_labels.get(current_state, "unknown"),
            "confidence": round(confidence, 4),
        }

    def is_model_fresh(self, max_age_days: int = 8) -> bool:
        if not os.path.exists(self._model_path):
            return False
        age = datetime.now(UTC).timestamp() - os.path.getmtime(self._model_path)
        return age < max_age_days * 86400

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_model(self) -> None:
        with open(self._model_path, "wb") as f:
            pickle.dump({
                "model":      self.model,
                "labels":     self.regime_labels,
                "train_mean": self._train_mean,
                "train_std":  self._train_std,
            }, f)

    def _load_model(self) -> None:
        if not os.path.exists(self._model_path):
            return
        try:
            with open(self._model_path, "rb") as f:
                data = pickle.load(f)
            self.model         = data["model"]
            self.regime_labels = data["labels"]
            self._train_mean   = data.get("train_mean")
            self._train_std    = data.get("train_std")
            logger.info("HMM model loaded | %s", self._model_path)
        except Exception as exc:
            logger.warning("Failed to load HMM model: %s", exc)
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_hmm_service.py -v
```

Expected: 6 tests PASS.

---

## Task 4: Add `generate_signal()` optional hook to `BaseStrategy`

**Context:** `ai_trading.py:339` calls `strategy_instance.generate_signal(market_data)` but `BaseStrategy` has no such method. The surrounding `try/except` silently swallows the `AttributeError`. Adding it as a documented optional hook makes the contract explicit.

**Files:**
- Modify: `backend/strategies/base_strategy.py`

**Step 1: Add method after `should_trade()`**

```python
    def generate_signal(self, market_data: dict) -> dict | None:
        """
        Optional rule-based signal override.

        Return a dict with keys matching TradingSignal to bypass LLM analysis,
        or return None to fall through to the LLM path.

        Required keys if returning a dict:
            action, entry, stop_loss, take_profit, confidence, rationale, timeframe
        """
        return None
```

No new tests needed — the existing pipeline tests implicitly cover the None fallthrough.

---

## Task 5: Add `regime_context` to `orchestrator.py`

**Files:**
- Modify: `backend/ai/orchestrator.py`

**Step 1: Update `_HUMAN` template — add `{regime_section}` between indicators and OHLCV**

Replace the existing `_HUMAN` string:

```python
_HUMAN = """Symbol: {symbol}
Timeframe: {timeframe}
Current Price: {current_price}

Indicators:
{indicators}
{regime_section}
Last 20 OHLCV candles (oldest → newest):
{ohlcv}
{positions_section}
{signals_section}
{chart_section}
{news_section}
{history_section}
Provide the trading signal JSON."""
```

**Step 2: Add `regime_context` parameter to `analyze_market()` signature**

After `trade_history_context: str | None = None,` add:

```python
    regime_context: str | None = None,
```

**Step 3: Add `regime_section` to `prompt_vars` dict**

In the `prompt_vars = { ... }` block, add alongside `news_section`:

```python
        "regime_section": (
            f"Market Regime (HMM):\n{regime_context}" if regime_context else ""
        ),
```

---

## Task 6: Inject HMM Step 5.5 + regime gate into `ai_trading.py`

**Files:**
- Modify: `backend/services/ai_trading.py`

**Step 1: Add `_REGIME_SIGNAL_FILTER` and `_apply_regime_filter()` after `_CACHE_TTL`**

```python
_REGIME_SIGNAL_FILTER: dict[str, set[str]] = {
    "trending_bullish":  {"BUY"},
    "trending_bearish":  {"SELL"},
    "ranging":           {"BUY", "SELL"},
    "high_volatility":   set(),
    "unknown":           {"BUY", "SELL"},
}


def _apply_regime_filter(signal: TradingSignal, regime: str) -> TradingSignal:
    """Return a new TradingSignal with action=HOLD if regime blocks the direction."""
    allowed = _REGIME_SIGNAL_FILTER.get(regime, {"BUY", "SELL"})
    if signal.action not in allowed:
        logger.info("Signal %s blocked by HMM regime '%s'", signal.action, regime)
        return TradingSignal(
            action="HOLD",
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence=signal.confidence,
            rationale=f"{signal.rationale} [HMM regime '{regime}' blocks {signal.action}]",
            timeframe=signal.timeframe,
        )
    return signal
```

**Step 2: Add class-level HMM cache to `AITradingService`**

```python
class AITradingService:
    _hmm_cache: dict[str, "HMMService"] = {}  # keyed by "SYMBOL_TF"
```

**Step 3: Insert Step 5.5 in `_run_pipeline()` after `indicators_computed` record**

After `await tracer.record("indicators_computed", ...)` and before `# ── 6. Fetch position context`:

```python
        # ── 5.5 HMM Regime detection ──────────────────────────────────────────
        t0 = time.monotonic()
        regime_info: dict = {"state": -1, "regime": "unknown", "confidence": 0.0}
        regime_context_str: str | None = None
        try:
            from services.hmm_service import HMMService
            cache_key = f"{symbol}_{tf_upper}"
            if cache_key not in AITradingService._hmm_cache:
                AITradingService._hmm_cache[cache_key] = HMMService(
                    symbol=symbol, timeframe=tf_upper
                )
            hmm_svc = AITradingService._hmm_cache[cache_key]
            if len(candles) >= 50:
                regime_info = hmm_svc.predict(candles)
                regime_context_str = (
                    f"Current market regime: **{regime_info['regime']}** "
                    f"(confidence: {regime_info['confidence']:.0%}). "
                    "Align your signal with this regime."
                )
        except Exception as exc:
            logger.warning("HMM predict failed | symbol=%s: %s", symbol, exc)
        await tracer.record(
            "hmm_regime",
            output_data=regime_info,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
```

**Step 4: Pass `regime_context` to `analyze_market()` in the LLM block (step 8)**

In the existing `analyze_market()` call, add after `trade_history_context=trade_history_context,`:

```python
                regime_context=regime_context_str,
```

**Step 5: Insert regime gate BEFORE journal save (between confidence gate and journal)**

After `await tracer.record("confidence_gate", ...)` and before `# ── 9. Persist AIJournal`:

```python
        # ── 9b. Regime gate ────────────────────────────────────────────────────
        action_before_regime = signal.action
        signal = _apply_regime_filter(signal, regime_info["regime"])
        await tracer.record(
            "regime_gate",
            input_data={"regime": regime_info["regime"], "action_in": action_before_regime},
            output_data={"action_out": signal.action},
        )
```

---

## Task 7: Create `hmm_retrain.py`

Fixes Bug #3 (DetachedInstanceError) and Bug #4 (async lazy-load).

**Files:**
- Create: `backend/services/hmm_retrain.py`

```python
# backend/services/hmm_retrain.py
"""HMM weekly retraining job — called by APScheduler."""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.config import settings
from core.security import decrypt
from db.models import AccountStrategy
from db.postgres import AsyncSessionLocal
from mt5.bridge import AccountCredentials, MT5Bridge
from services.hmm_service import HMMService

logger = logging.getLogger(__name__)

_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}
_HMM_TF      = "D1"
_HMM_TF_INT  = _TIMEFRAME_MAP["D1"]
_HMM_CANDLES = 365


async def retrain_all_hmm_models() -> None:
    """Retrain HMM for every active account/symbol combo. Called by APScheduler."""
    logger.info("HMM weekly retrain starting...")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AccountStrategy)
            .where(AccountStrategy.is_active.is_(True))
            # Bug Fix #4: eager-load both relationships inside the session
            .options(
                selectinload(AccountStrategy.strategy),
                selectinload(AccountStrategy.account),
            )
        )
        bindings = result.scalars().all()

        # Bug Fix #3: read all account attrs while session is still open,
        # then pass as plain dicts — never access ORM objects outside this block
        pairs: set[tuple[int, str]] = set()
        account_creds: dict[int, dict] = {}
        for b in bindings:
            if not b.account.is_active:
                continue
            symbols = json.loads(b.strategy.symbols or "[]")
            for sym in symbols:
                pairs.add((b.account_id, sym))
            if b.account_id not in account_creds:
                account_creds[b.account_id] = {
                    "login":              b.account.login,
                    "password_encrypted": b.account.password_encrypted,
                    "server":             b.account.server,
                    "mt5_path":           b.account.mt5_path,
                }

    for account_id, symbol in pairs:
        if account_id in account_creds:
            await _retrain_symbol(account_id, symbol, account_creds[account_id])

    logger.info("HMM weekly retrain complete | %d symbol pairs", len(pairs))


async def _retrain_symbol(account_id: int, symbol: str, creds_data: dict) -> None:
    try:
        password = decrypt(creds_data["password_encrypted"])
        creds = AccountCredentials(
            login=creds_data["login"],
            password=password,
            server=creds_data["server"],
            path=creds_data["mt5_path"] or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            candles = await bridge.get_rates(symbol, _HMM_TF_INT, _HMM_CANDLES)

        if not candles or len(candles) < 50:
            logger.warning("Not enough candles to retrain HMM | symbol=%s", symbol)
            return

        svc = HMMService(symbol=symbol, timeframe=_HMM_TF)
        svc.train(candles)

        # Invalidate pipeline cache so next run picks up the fresh model
        cache_key = f"{symbol}_{_HMM_TF}"
        from services.ai_trading import AITradingService
        AITradingService._hmm_cache.pop(cache_key, None)

        await _record_registry(symbol, len(candles), svc._model_path)

        logger.info(
            "HMM retrained | account=%d symbol=%s candles=%d",
            account_id, symbol, len(candles),
        )
    except Exception as exc:
        logger.error(
            "HMM retrain failed | account=%d symbol=%s: %s", account_id, symbol, exc
        )


async def _record_registry(symbol: str, candle_count: int, model_path: str) -> None:
    """Upsert a registry row so admins can see last retrain time per symbol."""
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from db.models import HMMModelRegistry
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(HMMModelRegistry).values(
                symbol=symbol,
                timeframe=_HMM_TF,
                trained_at=datetime.now(UTC),
                candle_count=candle_count,
                n_states=4,
                model_path=model_path,
                is_active=True,
            ).on_conflict_do_update(
                constraint="uq_hmm_symbol_timeframe",
                set_={
                    "trained_at":   datetime.now(UTC),
                    "candle_count": candle_count,
                    "model_path":   model_path,
                    "is_active":    True,
                },
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.warning("HMM registry record failed | symbol=%s: %s", symbol, exc)
```

---

## Task 8: Register weekly retrain job in `scheduler.py`

**Files:**
- Modify: `backend/services/scheduler.py`

**Step 1: Add job at end of `start_scheduler()` before the final `logger.info`**

```python
    # Weekly HMM retrain — every Sunday 01:00 UTC
    from services.hmm_retrain import retrain_all_hmm_models
    _scheduler.add_job(
        retrain_all_hmm_models,
        trigger=CronTrigger(day_of_week="sun", hour=1, minute=0, timezone="UTC"),
        id="hmm_weekly_retrain",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("HMM weekly retrain job registered (Sunday 01:00 UTC)")
```

---

## Task 9: Create `HMMRegimeStrategy`

**Files:**
- Create: `backend/strategies/hmm_strategy.py`

```python
# backend/strategies/hmm_strategy.py
"""HMM Regime-Gated Strategy — BaseStrategy subclass."""
from __future__ import annotations

from strategies.base_strategy import BaseStrategy


class HMMRegimeStrategy(BaseStrategy):
    """Returns HOLD during high_volatility; otherwise falls through to LLM
    (which receives regime context in its prompt from Step 5.5).

    Register in the UI:
        type=Code, module=strategies.hmm_strategy, class=HMMRegimeStrategy
    """

    symbols   = ["EURUSD", "XAUUSD"]
    timeframe = "D1"

    def system_prompt(self) -> str:
        return (
            "You are a regime-aware trading analyst. "
            "The market data context includes the current HMM regime. "
            "Only BUY in bullish regimes, only SELL in bearish regimes, "
            "scalp both directions when ranging, and always HOLD in high-volatility regimes."
        )

    def generate_signal(self, market_data: dict) -> dict | None:
        candles = market_data.get("candles", [])
        symbol  = market_data.get("symbol", "")
        tf      = market_data.get("timeframe", "D1")

        if len(candles) < 50:
            return None

        try:
            from services.hmm_service import HMMService
            svc    = HMMService(symbol=symbol, timeframe=tf)
            regime = svc.predict(candles)
        except Exception:
            return None

        if regime["regime"] == "high_volatility":
            return {
                "action":      "HOLD",
                "entry":       market_data.get("current_price", 0.0),
                "stop_loss":   0.0,
                "take_profit": 0.0,
                "confidence":  1.0,
                "rationale":   "HMM regime: high_volatility — no new trades",
                "timeframe":   tf,
            }

        return None  # LLM path — regime injected into prompt by Step 5.5
```

---

## Task 10: Add `HMMModelRegistry` to `db/models.py` and migrate

**Files:**
- Modify: `backend/db/models.py`

**Step 1: Add model at end of `models.py`**

```python
class HMMModelRegistry(Base):
    __tablename__ = "hmm_model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    candle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_states: Mapped[int] = mapped_column(Integer, default=4)
    model_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", name="uq_hmm_symbol_timeframe"),
    )
```

**Step 2: Generate migration**

```bash
cd backend && uv run alembic revision --autogenerate -m "add hmm_model_registry"
```

Expected: new file created under `backend/alembic/versions/`.

**Step 3: Apply migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade ... -> <hash>, add hmm_model_registry`

---

## Task 11: Run full test suite

```bash
cd backend && uv run pytest -v
```

Expected: all pre-existing tests still pass + 9 new HMM tests pass. Zero regressions.

---

## Manual Smoke Test (after all tasks)

1. Start backend: `uv run uvicorn main:app --reload --port 8000`
2. Trigger a pipeline run via the UI or API.
3. Check `pipeline_steps` for a row with `step_name = "hmm_regime"` — shows `{"regime": "unknown"}` until a model is trained (graceful degradation working).
4. Run initial training from a Python shell:
   ```python
   from services.hmm_retrain import retrain_all_hmm_models
   import asyncio; asyncio.run(retrain_all_hmm_models())
   ```
5. Re-trigger pipeline run — `hmm_regime` step now shows a real regime + confidence, and `regime_gate` step shows whether any signal was blocked.
6. Confirm `hmm_model_registry` table has one row per symbol.
