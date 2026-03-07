"""Gartley Pattern validator.

Bullish Gartley: X(high) → A(low) → B(high) → C(low) → D(low) — enter BUY at D
Bearish Gartley: X(low) → A(high) → B(low) → C(high) → D(high) — enter SELL at D

Ratios:
  AB/XA: 0.618
  BC/AB: 0.382 – 0.886
  CD/BC: 0.618 – 1.618
  D retraces XA: 0.786
"""
from __future__ import annotations
from strategies.harmonic.swing_detector import Pivot
from strategies.harmonic.patterns.base_pattern import BaseHarmonicPattern, PatternResult


class Gartley(BaseHarmonicPattern):
    name = "Gartley"

    def validate(self, x: Pivot, a: Pivot, b: Pivot, c: Pivot, d: Pivot) -> PatternResult | None:
        xa = abs(a.price - x.price)
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        cd = abs(d.price - c.price)

        if xa < 1e-10 or ab < 1e-10 or bc < 1e-10:
            return None

        ab_xa = ab / xa
        bc_ab = bc / ab
        cd_bc = cd / bc if bc > 1e-10 else 0.0
        d_xa  = self._retracement_ratio(d.price, a.price, x.price)

        if not self._ratio_in_range(ab_xa, 0.618, 0.618):
            return None
        if not self._ratio_in_range(bc_ab, 0.382, 0.886):
            return None
        if not self._ratio_in_range(cd_bc, 0.618, 1.618):
            return None
        if not self._ratio_in_range(d_xa, 0.786, 0.786):
            return None

        # Determine direction: bullish if X is high (price fell XA then recovered)
        direction = "bullish" if x.type == "high" else "bearish"

        accuracy = (
            self._ratio_accuracy_score(ab_xa, 0.618) +
            self._ratio_accuracy_score(bc_ab, 0.618) +
            self._ratio_accuracy_score(cd_bc, 1.272) +
            self._ratio_accuracy_score(d_xa,  0.786)
        ) / 4.0

        return PatternResult(
            pattern_name=self.name,
            direction=direction,
            points={"X": x, "A": a, "B": b, "C": c, "D": d},
            ratios={"AB/XA": ab_xa, "BC/AB": bc_ab, "CD/BC": cd_bc, "D/XA": d_xa},
            expected_ratios={
                "AB/XA": (0.618, 0.618), "BC/AB": (0.382, 0.886),
                "CD/BC": (0.618, 1.618), "D/XA": (0.786, 0.786),
            },
            ratio_accuracy=accuracy,
            prz_high=max(d.price, d.price * 1.001),
            prz_low=min(d.price, d.price * 0.999),
        )
