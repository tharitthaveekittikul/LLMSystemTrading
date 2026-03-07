"""ABCD Pattern (base 4-point pattern — no X point).

BC/AB: 0.618 – 0.786
CD/BC: 1.272 – 1.618  (CD ≈ AB in length)
validate() accepts (a, b, c, d) — pass x=None or use the 4-point signature.
"""
from strategies.harmonic.patterns.base_pattern import BaseHarmonicPattern, PatternResult
from strategies.harmonic.swing_detector import Pivot


class ABCD(BaseHarmonicPattern):
    name = "ABCD"

    def validate(self, x: Pivot, a: Pivot, b: Pivot, c: Pivot, d: Pivot) -> PatternResult | None:
        """x is ignored for ABCD — uses a,b,c,d only."""
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        cd = abs(d.price - c.price)
        if ab < 1e-10 or bc < 1e-10: return None

        bc_ab = bc / ab
        cd_bc = cd / bc if bc > 1e-10 else 0.0

        if not self._ratio_in_range(bc_ab, 0.618, 0.786): return None
        if not self._ratio_in_range(cd_bc, 1.272, 1.618): return None

        direction = "bullish" if a.type == "high" else "bearish"
        accuracy = (self._ratio_accuracy_score(bc_ab, 0.618) +
                    self._ratio_accuracy_score(cd_bc, 1.272)) / 2.0
        return PatternResult(
            pattern_name=self.name, direction=direction,
            points={"A": a, "B": b, "C": c, "D": d},
            ratios={"BC/AB": bc_ab, "CD/BC": cd_bc},
            expected_ratios={"BC/AB": (0.618, 0.786), "CD/BC": (1.272, 1.618)},
            ratio_accuracy=accuracy, prz_high=d.price * 1.001, prz_low=d.price * 0.999,
        )
