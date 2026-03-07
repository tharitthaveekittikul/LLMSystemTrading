"""Abstract base for all harmonic pattern validators."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from strategies.harmonic.swing_detector import Pivot


@dataclass
class PatternResult:
    pattern_name: str
    direction: Literal["bullish", "bearish"]
    points: dict[str, Pivot]             # {"X": pivot, "A": ..., "B": ..., "C": ..., "D": ...}
    ratios: dict[str, float]             # actual computed ratios
    expected_ratios: dict[str, tuple]    # (min, max) per ratio key
    ratio_accuracy: float                # 0.0–1.0, how close ratios are to ideal
    quality_score: float = 0.0          # set by scanner after H1 alignment check
    prz_high: float = 0.0
    prz_low: float = 0.0


class BaseHarmonicPattern(ABC):
    name: str = ""
    tolerance: float = 0.05   # ±5% on all ratio checks

    @abstractmethod
    def validate(self, x: Pivot, a: Pivot, b: Pivot, c: Pivot, d: Pivot) -> PatternResult | None:
        """Return PatternResult if the XABCD pivots form this pattern, else None."""
        ...

    def _ratio_in_range(self, actual: float, expected_min: float,
                        expected_max: float) -> bool:
        """Check if actual ratio is within [expected_min, expected_max] ± tolerance."""
        lo = expected_min * (1.0 - self.tolerance)
        hi = expected_max * (1.0 + self.tolerance)
        return lo <= actual <= hi

    def _ratio_accuracy_score(self, actual: float, ideal: float) -> float:
        """Return 1.0 for perfect match, approaching 0 as deviation increases."""
        if ideal == 0:
            return 0.0
        return max(0.0, 1.0 - abs(actual - ideal) / ideal)

    def _fib_ratio(self, leg_start: float, leg_end: float, ref_start: float,
                   ref_end: float) -> float:
        """Compute ratio = abs(leg) / abs(ref). Returns 0 if ref is zero."""
        ref = abs(ref_end - ref_start)
        if ref < 1e-10:
            return 0.0
        return abs(leg_end - leg_start) / ref

    def _retracement_ratio(self, point: float, start: float, end: float) -> float:
        """Compute how far 'point' retraces the start→end move. 0=no retrace, 1=full."""
        move = abs(end - start)
        if move < 1e-10:
            return 0.0
        return abs(point - end) / move
