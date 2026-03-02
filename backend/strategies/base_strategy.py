from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from ai.orchestrator import TradingSignal


class BaseStrategy(ABC):
    """
    Abstract base for all code-based trading strategies.

    To create a new strategy:
    1. Create backend/strategies/your_strategy.py inheriting this class
    2. Implement system_prompt() and optionally override risk methods
    3. Register in the UI: type=Code, module=strategies.your_strategy, class=YourClass
    4. Restart the backend once — importlib will pick it up
    5. Bind to an account — scheduler starts the job immediately
    """

    symbols: ClassVar[list[str]] = []
    timeframe: ClassVar[str] = "M15"
    trigger_type: ClassVar[str] = "candle_close"   # "interval" | "candle_close"
    interval_minutes: ClassVar[int] = 15

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the full LLM system prompt for this strategy."""
        ...

    # ── Risk overrides — return None to use account/system defaults ─────────

    def lot_size(self) -> float | None:
        return None

    def sl_pips(self) -> float | None:
        return None

    def tp_pips(self) -> float | None:
        return None

    def news_filter(self) -> bool:
        return True

    # ── Signal gate ──────────────────────────────────────────────────────────

    def should_trade(self, signal: "TradingSignal") -> bool:
        """
        Return False to skip order execution for this signal.
        The signal is still logged to AIJournal regardless.
        """
        return signal.action != "HOLD"

    def generate_signal(self, market_data: dict) -> dict | None:
        """
        Optional rule-based signal override.

        Return a dict with keys matching TradingSignal to bypass LLM analysis,
        or return None to fall through to the LLM path.

        Required keys if returning a dict:
            action, entry, stop_loss, take_profit, confidence, rationale, timeframe
        """
        return None
