# HMM (Hidden Markov Model) Integration Roadmap

> **Created**: 2026-03-02  
> **Project**: LLMSystemTrading  
> **Goal**: Integrate a Hidden Markov Model for market regime detection and retrain it every week automatically via the existing APScheduler infrastructure.

---

## 1. Overview & Motivation

The current trading pipeline relies on two signal paths:

| Path                | How it works                               | Limitation                            |
| ------------------- | ------------------------------------------ | ------------------------------------- |
| **LLM path**        | GPT/Gemini analyzes OHLCV + indicators     | No structural market regime awareness |
| **Rule-based path** | `BaseStrategy.generate_signal()` in Python | Static rules, not adaptive            |

**What HMM adds:**  
A Hidden Markov Model classifies the _hidden market regime_ (e.g., Trending Up, Trending Down, Ranging, High-Volatility) from observable price features. This regime label then:

- **Filters** or **amplifies** trading signals from both the LLM and rule-based paths
- **Adapts** to changing market structure by retraining every week on fresh data

---

## 2. Core Concepts for This Project

### What HMM Detects

| Hidden State           | Observable signature                                       |
| ---------------------- | ---------------------------------------------------------- |
| **Trending Bullish**   | Positive returns, low volatility, strong momentum          |
| **Trending Bearish**   | Negative returns, low volatility, strong downward momentum |
| **Ranging / Sideways** | Near-zero returns, low volatility, mean-reverting          |
| **High Volatility**    | Large absolute returns, high ATR, spike in volume          |

### Feature Inputs (per candle)

- Log return: `log(close_t / close_{t-1})`
- Realized volatility (rolling 14-bar std of log returns)
- ATR (14) normalized by price
- Volume ratio: `volume / rolling_mean_volume(20)`

### Library: `hmmlearn`

```
pip install hmmlearn
```

Uses `GaussianHMM` with `n_components` = 4 (one per regime class).

---

## 3. Integration Architecture

```
MT5 (OHLCV data)
       │
       ▼
HMMFeatureExtractor           ← new: services/hmm_features.py
       │  (log_return, vol, ATR_norm, vol_ratio)
       ▼
HMMService                    ← new: services/hmm_service.py
 ├── train(candles) → save model to disk / Redis
 ├── predict(candles) → current_regime (int + label str)
 └── is_model_fresh() → bool
       │  regime: "trending_bullish" | "trending_bearish" | "ranging" | "high_volatility"
       ▼
AITradingService._run_pipeline()   ← modified: services/ai_trading.py
 ├── Step 5.5 (NEW): hmm_service.predict → regime
 ├── Step 7: rule-based signal → apply regime_filter()
 └── Step 8: LLM prompt → inject regime context string
       │
       ▼
HMMStrategy (optional)        ← new: strategies/hmm_strategy.py
 └── BaseStrategy subclass that uses HMM directly as signal

HMMRetrainJob                 ← new: services/hmm_retrain.py
 └── Runs weekly via APScheduler → fetches D1 candles → trains → saves model
```

---

## 4. Implementation Phases

---

### Phase 1 — HMM Core Library (Week 1–2)

**Goal**: Train and persist a working HMM model manually.

#### 4.1 New Files

**`backend/services/hmm_features.py`**

```python
"""Feature extraction for HMM training and inference."""
import numpy as np

def extract_features(candles: list[dict]) -> np.ndarray:
    """
    Returns shape (n_samples, 4) array:
      col 0: log_return
      col 1: realized_vol (14-bar rolling std of log_return)
      col 2: atr_norm (ATR14 / close)
      col 3: volume_ratio (volume / rolling_mean_vol_20)
    """
    closes  = np.array([c["close"]       for c in candles], dtype=float)
    highs   = np.array([c["high"]        for c in candles], dtype=float)
    lows    = np.array([c["low"]         for c in candles], dtype=float)
    volumes = np.array([c["tick_volume"] for c in candles], dtype=float)

    log_ret = np.diff(np.log(closes), prepend=np.log(closes[0]))

    # Realized vol: rolling 14-bar std
    rvol = np.array([
        log_ret[max(0, i-13):i+1].std() if i >= 13 else log_ret[:i+1].std()
        for i in range(len(log_ret))
    ])

    # ATR 14
    tr = np.maximum(highs - lows,
         np.maximum(abs(highs - np.roll(closes, 1)),
                    abs(lows  - np.roll(closes, 1))))
    atr = np.array([tr[max(0,i-13):i+1].mean() for i in range(len(tr))])
    atr_norm = atr / closes

    # Volume ratio
    vol_mean = np.array([
        volumes[max(0,i-19):i+1].mean() for i in range(len(volumes))
    ])
    vol_ratio = volumes / np.where(vol_mean > 0, vol_mean, 1)

    return np.column_stack([log_ret, rvol, atr_norm, vol_ratio])
```

**`backend/services/hmm_service.py`**

```python
"""HMM Market Regime Service."""
import pickle, logging, os
from datetime import datetime, UTC
import numpy as np
from hmmlearn import hmm

from services.hmm_features import extract_features

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "hmm_models")
N_STATES  = 4

REGIME_LABELS = {
    # Assigned after first training by inspecting state means
    # Override in config once you've examined the trained model
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
        self._model_path = os.path.join(
            MODEL_DIR, f"hmm_{symbol}_{timeframe}.pkl"
        )
        os.makedirs(MODEL_DIR, exist_ok=True)
        self._load_model()

    # ── Training ─────────────────────────────────────────────────────────────

    def train(self, candles: list[dict]) -> None:
        """Train on historical candles (minimum 100 recommended)."""
        if len(candles) < 50:
            raise ValueError("Need at least 50 candles to train HMM")

        X = extract_features(candles)
        X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)  # standardize

        model = hmm.GaussianHMM(
            n_components=N_STATES,
            covariance_type="diag",
            n_iter=200,
            random_state=42,
        )
        model.fit(X)

        self.model = model
        self._label_states()
        self._save_model()
        logger.info(
            "HMM trained | symbol=%s timeframe=%s candles=%d",
            self.symbol, self.timeframe, len(candles),
        )

    def _label_states(self) -> None:
        """Auto-label states by mean log_return of each hidden state."""
        if self.model is None:
            return
        means = self.model.means_[:, 0]  # col 0 = log_return
        ranked = np.argsort(means)  # ascending return
        # ranked[0]=most bearish, ranked[-1]=most bullish, etc.
        global REGIME_LABELS
        REGIME_LABELS = {
            int(ranked[0]): "trending_bearish",
            int(ranked[1]): "ranging",
            int(ranked[2]): "ranging",      # two 'ranging' states possible
            int(ranked[3]): "trending_bullish",
        }
        # Override middle states by volatility (col 1)
        vols = self.model.means_[:, 1]
        mid_states = [int(ranked[1]), int(ranked[2])]
        high_vol_state = mid_states[int(np.argmax([vols[s] for s in mid_states]))]
        REGIME_LABELS[high_vol_state] = "high_volatility"

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, candles: list[dict]) -> dict:
        """Predict current market regime from recent candles.

        Returns:
            {
                "state": int,
                "regime": str,   # e.g. "trending_bullish"
                "confidence": float,  # posterior probability of predicted state
            }
        """
        if self.model is None:
            return {"state": -1, "regime": "unknown", "confidence": 0.0}

        X = extract_features(candles[-max(50, len(candles)):])
        X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)

        _, state_sequence = self.model.decode(X, algorithm="viterbi")
        current_state = int(state_sequence[-1])

        # Posterior probability of current state given all observations
        log_posteriors = self.model.predict_proba(X)
        confidence = float(log_posteriors[-1, current_state])

        return {
            "state": current_state,
            "regime": REGIME_LABELS.get(current_state, "unknown"),
            "confidence": round(confidence, 4),
        }

    def is_model_fresh(self, max_age_days: int = 8) -> bool:
        """Check if the saved model is recent enough."""
        if not os.path.exists(self._model_path):
            return False
        age = (datetime.now(UTC).timestamp() - os.path.getmtime(self._model_path))
        return age < max_age_days * 86400

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_model(self) -> None:
        with open(self._model_path, "wb") as f:
            pickle.dump({"model": self.model, "labels": REGIME_LABELS}, f)

    def _load_model(self) -> None:
        if os.path.exists(self._model_path):
            try:
                with open(self._model_path, "rb") as f:
                    data = pickle.load(f)
                self.model = data["model"]
                global REGIME_LABELS
                REGIME_LABELS = data["labels"]
                logger.info("HMM model loaded | %s", self._model_path)
            except Exception as exc:
                logger.warning("Failed to load HMM model: %s", exc)
```

#### 4.2 Dependency

Add to `backend/pyproject.toml`:

```toml
[project.dependencies]
hmmlearn = ">=0.3.2"
```

Run:

```bash
cd backend && uv add hmmlearn
```

---

### Phase 2 — Integrate Regime into `ai_trading.py` (Week 2–3)

**Goal**: The existing `AITradingService._run_pipeline()` injects regime context at two places.

#### 2a. After Step 5 (indicators), add Step 5.5 — Regime Detection

```python
# ── 5.5 HMM Regime detection ─────────────────────────────────────────────
t0 = time.monotonic()
regime_info = {"state": -1, "regime": "unknown", "confidence": 0.0}
try:
    from services.hmm_service import HMMService
    hmm_svc = HMMService(symbol=symbol, timeframe=tf_upper)
    if len(candles) >= 50:
        regime_info = hmm_svc.predict(candles)
except Exception as exc:
    logger.warning("HMM predict failed | symbol=%s: %s", symbol, exc)
await tracer.record(
    "hmm_regime",
    output_data=regime_info,
    duration_ms=int((time.monotonic() - t0) * 1000),
)
```

#### 2b. Rule-based path — apply `regime_filter()`

```python
# helpers (add to ai_trading.py)

_REGIME_SIGNAL_FILTER: dict[str, set[str]] = {
    "trending_bullish":  {"BUY"},           # only take BUY trades
    "trending_bearish":  {"SELL"},          # only take SELL trades
    "ranging":           {"BUY", "SELL"},   # scalp both directions
    "high_volatility":   set(),             # no trades — too risky
    "unknown":           {"BUY", "SELL"},   # no filter if model missing
}

def _apply_regime_filter(signal: TradingSignal, regime: str) -> TradingSignal:
    allowed = _REGIME_SIGNAL_FILTER.get(regime, {"BUY", "SELL"})
    if signal.action not in allowed:
        logger.info(
            "Signal %s blocked by HMM regime '%s'", signal.action, regime
        )
        signal.action = "HOLD"
    return signal
```

Then after confidence gate:

```python
# ── 9b. Regime gate ──────────────────────────────────────────────────────
signal = _apply_regime_filter(signal, regime_info["regime"])
```

#### 2c. LLM path — inject regime into prompt context

In the `analyze_market()` call, add:

```python
regime_context = (
    f"Current market regime detected by HMM: **{regime_info['regime']}** "
    f"(confidence: {regime_info['confidence']:.0%}). "
    "Align your signal with this regime."
)
llm_result = await analyze_market(
    ...
    news_context=news_context_str,
    regime_context=regime_context,   # ← new kwarg
    ...
)
```

Update `ai/orchestrator.py` to accept and embed `regime_context` in the system prompt.

---

### Phase 3 — HMM Strategy Class (Week 3)

**Goal**: Expose HMM as a standalone `BaseStrategy` subclass for pure regime-gating use.

**`backend/strategies/hmm_strategy.py`**

```python
"""HMM Regime-Gated Strategy — extends BaseStrategy."""
from strategies.base import BaseStrategy
from services.hmm_service import HMMService


class HMMRegimeStrategy(BaseStrategy):
    """Generates no signal itself; returns None to let the LLM analyse,
    but restricts allowed actions based on the current detected regime.

    When used with the scheduler, this strategy:
    1. Detects the current regime via HMM
    2. Returns HOLD if the regime is 'high_volatility'
    3. Returns None to fall back to the LLM for BUY/SELL decisions
       (LLM will receive regime context in its prompt)
    """

    symbols = ["EURUSD", "XAUUSD"]  # override per strategy DB record

    def generate_signal(self, market_data: dict) -> dict | None:
        candles = market_data["candles"]
        symbol  = market_data["symbol"]
        tf      = market_data["timeframe"]

        try:
            svc    = HMMService(symbol=symbol, timeframe=tf)
            regime = svc.predict(candles)
        except Exception:
            return None  # fallback to LLM

        if regime["regime"] == "high_volatility":
            return {
                "action":      "HOLD",
                "entry":       market_data["current_price"],
                "stop_loss":   0.0,
                "take_profit": 0.0,
                "confidence":  1.0,
                "rationale":   f"HMM regime: high_volatility — no new trades",
                "timeframe":   tf,
            }

        return None  # let LLM decide; regime injected into LLM prompt separately
```

---

### Phase 4 — Weekly Retraining Job (Week 3–4)

**Goal**: Every Sunday at 01:00 UTC, fetch 1 year of D1 candles and retrain the HMM for each active symbol/account pair.

#### 4.1 Retraining Service

**`backend/services/hmm_retrain.py`**

```python
"""HMM weekly retraining job — called by APScheduler."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Account, AccountStrategy
from db.postgres import AsyncSessionLocal
from core.security import decrypt
from core.config import settings
from mt5.bridge import AccountCredentials, MT5Bridge
from services.hmm_service import HMMService

logger = logging.getLogger(__name__)

_TIMEFRAME_MAP = {"M15": 15, "H1": 16385, "H4": 16388, "D1": 16408}
_HMM_TF = "D1"
_HMM_TF_INT = _TIMEFRAME_MAP["D1"]
_HMM_CANDLE_COUNT = 365  # ~1 year of daily candles


async def retrain_all_hmm_models() -> None:
    """Fetch candles and retrain HMM for all active account/symbol combos."""
    logger.info("HMM weekly retrain starting...")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AccountStrategy)
            .where(AccountStrategy.is_active.is_(True))
        )
        bindings = result.scalars().all()

    # Collect unique (account, symbol) pairs
    pairs: set[tuple[int, str]] = set()
    for b in bindings:
        import json
        symbols = json.loads(b.strategy.symbols or "[]") if hasattr(b, 'strategy') else []
        for sym in symbols:
            pairs.add((b.account_id, sym))

    for account_id, symbol in pairs:
        await _retrain_symbol(account_id, symbol)

    logger.info("HMM weekly retrain complete | %d symbol pairs", len(pairs))


async def _retrain_symbol(account_id: int, symbol: str) -> None:
    async with AsyncSessionLocal() as db:
        account = await db.get(Account, account_id)
        if not account or not account.is_active:
            return

    try:
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            candles = await bridge.get_rates(symbol, _HMM_TF_INT, _HMM_CANDLE_COUNT)

        if not candles or len(candles) < 50:
            logger.warning("Not enough candles to retrain HMM | symbol=%s", symbol)
            return

        svc = HMMService(symbol=symbol, timeframe=_HMM_TF)
        svc.train(candles)
        logger.info("HMM retrained | account=%d symbol=%s candles=%d",
                    account_id, symbol, len(candles))

    except Exception as exc:
        logger.error("HMM retrain failed | account=%d symbol=%s: %s",
                     account_id, symbol, exc)
```

#### 4.2 Register in `scheduler.py`

Add to `start_scheduler()`:

```python
from apscheduler.triggers.cron import CronTrigger
from services.hmm_retrain import retrain_all_hmm_models

# Weekly HMM retrain — every Sunday 01:00 UTC
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

### Phase 5 — Database & Admin (Week 4)

#### 5.1 New DB Table: `hmm_model_registry`

Add to `db/models.py`:

```python
class HMMModelRegistry(Base):
    __tablename__ = "hmm_model_registry"

    id           = Column(Integer, primary_key=True)
    symbol       = Column(String(20), nullable=False)
    timeframe    = Column(String(10), nullable=False)
    trained_at   = Column(DateTime(timezone=True), server_default=func.now())
    candle_count = Column(Integer)
    n_states     = Column(Integer, default=4)
    score        = Column(Float)           # log-likelihood score
    model_path   = Column(String(255))
    is_active    = Column(Boolean, default=True)
```

Generate migration:

```bash
cd backend && alembic revision --autogenerate -m "add hmm_model_registry"
alembic upgrade head
```

#### 5.2 API Endpoint (optional, Week 5)

`GET /api/hmm/regime/{symbol}?timeframe=D1`

Returns current regime for monitoring dashboard.

---

### Phase 6 — Backtest Integration (Week 4–5)

**Goal**: BacktestEngine can optionally run with HMM regime filter applied per candle.

In `backtest_engine.py`, add optional `hmm_service` parameter to `run()`:

```python
async def run(
    self,
    candles,
    strategy,
    config,
    progress_cb=None,
    hmm_service=None,          # ← new
) -> dict:
    ...
    for i, candle in enumerate(candles):
        # Regime check before signal
        regime = "unknown"
        if hmm_service and i >= 50:
            window = candles[max(0, i-49):i+1]
            regime_info = hmm_service.predict(window)
            regime = regime_info["regime"]

        # Skip high_volatility in backtest mode
        if regime == "high_volatility":
            continue

        ...existing signal logic...
```

This allows backtesting the **exact same regime-gated logic** that runs live — no strategy code changes needed.

---

## 5. File Change Summary

| Status    | File                                                 | Purpose                                     |
| --------- | ---------------------------------------------------- | ------------------------------------------- |
| 🆕 NEW    | `backend/services/hmm_features.py`                   | Feature extraction (log return, vol, ATR)   |
| 🆕 NEW    | `backend/services/hmm_service.py`                    | Train, predict, persist HMM model           |
| 🆕 NEW    | `backend/services/hmm_retrain.py`                    | Weekly retrain job logic                    |
| 🆕 NEW    | `backend/strategies/hmm_strategy.py`                 | BaseStrategy subclass for HMM regime gating |
| 🔧 MODIFY | `backend/services/ai_trading.py`                     | Step 5.5 regime detect, apply regime filter |
| 🔧 MODIFY | `backend/services/scheduler.py`                      | Register weekly retrain CronTrigger         |
| 🔧 MODIFY | `backend/ai/orchestrator.py`                         | Accept `regime_context` kwarg in prompt     |
| 🔧 MODIFY | `backend/services/backtest_engine.py`                | Optional `hmm_service` param                |
| 🔧 MODIFY | `backend/db/models.py`                               | Add `HMMModelRegistry` table                |
| 🔧 MODIFY | `backend/pyproject.toml`                             | Add `hmmlearn` dependency                   |
| 🆕 NEW    | `backend/alembic/versions/xxx_hmm_model_registry.py` | DB migration                                |

---

## 6. Timeline

```
Week 1  ──  Phase 1: hmm_features.py + hmm_service.py + manual training test
Week 2  ──  Phase 2: Integrate into ai_trading.py pipeline (Step 5.5 + regime gate)
Week 3  ──  Phase 3: HMMRegimeStrategy class + Phase 4: hmm_retrain.py + scheduler job
Week 4  ──  Phase 5: DB model registry + API endpoint
Week 5  ──  Phase 6: Backtest integration + end-to-end testing
Week 6  ──  Monitoring dashboard widget showing current regime per symbol
```

---

## 7. Verification Plan

### Unit Tests (add to `backend/tests/`)

```python
# tests/test_hmm_service.py
def test_extract_features_shape(sample_candles_200):
    X = extract_features(sample_candles_200)
    assert X.shape == (200, 4)

def test_hmm_train_predict(sample_candles_200):
    svc = HMMService("EURUSD", "D1")
    svc.train(sample_candles_200)
    result = svc.predict(sample_candles_200[-50:])
    assert result["regime"] in {"trending_bullish", "trending_bearish", "ranging", "high_volatility"}
    assert 0.0 <= result["confidence"] <= 1.0

def test_retrain_persist_reload(sample_candles_200, tmp_path):
    svc = HMMService("USDJPY", "D1")
    svc._model_path = str(tmp_path / "test_model.pkl")
    svc.train(sample_candles_200)
    svc2 = HMMService("USDJPY", "D1")
    svc2._model_path = svc._model_path
    svc2._load_model()
    assert svc2.model is not None
```

### Integration Tests

- Trigger weekly retrain job manually via scheduler:
  ```python
  from services.hmm_retrain import retrain_all_hmm_models
  await retrain_all_hmm_models()
  ```
- Verify `data/hmm_models/hmm_EURUSD_D1.pkl` is created/updated.
- Run a live `analyze_and_trade()` and check `pipeline_steps` table for `hmm_regime` step.

### Backtest Validation

- Run backtest with `hmm_service=None` (baseline) vs `hmm_service=HMMService(...)` (filtered).
- Compare: total trades, win rate, max drawdown, Sharpe ratio.
- Expect: fewer trades but higher win rate in trending regimes.

---

## 8. Key Decisions & Trade-offs

| Decision                   | Chosen approach                      | Alternative                               |
| -------------------------- | ------------------------------------ | ----------------------------------------- |
| **HMM library**            | `hmmlearn` (scikit-learn compatible) | `pomegranate`, custom Baum-Welch          |
| **Timeframe for training** | D1 (daily) — captures macro regimes  | H4 for higher resolution                  |
| **Model persistence**      | Pickle file in `data/hmm_models/`    | Redis (faster but memory cost)            |
| **Retrain frequency**      | Weekly (Sundays 01:00 UTC)           | Daily (overkill; regime changes slowly)   |
| **Regime count**           | 4 states                             | 2 (simple bull/bear) or 6 (more granular) |
| **Regime gate behavior**   | Block signals that oppose regime     | Confidence penalty instead of hard block  |
| **high_volatility regime** | No trades (HOLD)                     | Reduce lot size by 50% instead            |

---

## 9. Risk Considerations

> ⚠️ **Regime detection lag**: HMM detects regime _after_ a regime change begins — expect 1–5 bars of lag on shifts. Consider 1-bar confirmation before acting.

> ⚠️ **Overfitting**: HMM trained on 1 year D1 = ~252 bars. This is sufficient for 4 states but monitor model log-likelihood on test set.

> ⚠️ **State label instability**: State indices (0,1,2,3) from hmmlearn are not semantically stable across retrains — always remap via `_label_states()` after each train.

> ⚠️ **Backward compatibility**: The HMM step is wrapped in `try/except` — pipeline degrades gracefully to `regime="unknown"` (no filtering) if model is unavailable.
