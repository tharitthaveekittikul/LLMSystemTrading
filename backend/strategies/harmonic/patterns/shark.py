"""Shark Pattern — uses 5 points O, X, A, B, C.

The 'D' entry point is at C in standard notation.
Ratios:
  XA/OX: 0.446 – 0.618  (AB relative to OX)
  BC/XA: 1.130 – 1.618  (extension of XA)
  C retraces OX: 0.886 – 1.130
"""
from strategies.harmonic.swing_detector import Pivot
from strategies.harmonic.patterns.base_pattern import BaseHarmonicPattern, PatternResult


class Shark(BaseHarmonicPattern):
    name = "Shark"

    def validate(self, o: Pivot, x: Pivot, a: Pivot, b: Pivot, c: Pivot) -> PatternResult | None:
        """Note: validate() signature uses o,x,a,b,c for Shark (not x,a,b,c,d)."""
        ox = abs(x.price - o.price)
        xa = abs(a.price - x.price)
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        if ox < 1e-10 or xa < 1e-10 or ab < 1e-10: return None

        xa_ox = xa / ox
        bc_xa = bc / xa if xa > 1e-10 else 0.0
        c_ox_retrace = self._retracement_ratio(c.price, o.price, x.price)

        if not self._ratio_in_range(xa_ox, 0.446, 0.618): return None
        if not self._ratio_in_range(bc_xa, 1.130, 1.618): return None
        if not self._ratio_in_range(c_ox_retrace, 0.886, 1.130): return None

        direction = "bullish" if o.type == "high" else "bearish"
        accuracy = (self._ratio_accuracy_score(xa_ox, 0.500) +
                    self._ratio_accuracy_score(bc_xa, 1.130) +
                    self._ratio_accuracy_score(c_ox_retrace, 0.886)) / 3.0
        return PatternResult(
            pattern_name=self.name, direction=direction,
            points={"O": o, "X": x, "A": a, "B": b, "C": c},
            ratios={"XA/OX": xa_ox, "BC/XA": bc_xa, "C/OX": c_ox_retrace},
            expected_ratios={"XA/OX": (0.446, 0.618), "BC/XA": (1.130, 1.618),
                             "C/OX": (0.886, 1.130)},
            ratio_accuracy=accuracy,
            prz_high=c.price * 1.001, prz_low=c.price * 0.999,
        )
