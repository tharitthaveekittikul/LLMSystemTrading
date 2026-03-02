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

    # -- Training -------------------------------------------------------------

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

    # -- Prediction -----------------------------------------------------------

    def predict(self, candles: list[dict]) -> dict:
        """Predict current regime. Returns {"state", "regime", "confidence"}."""
        if self.model is None or self._train_mean is None:
            return {"state": -1, "regime": "unknown", "confidence": 0.0}

        window = candles[-50:]
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

    # -- Persistence ----------------------------------------------------------

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
