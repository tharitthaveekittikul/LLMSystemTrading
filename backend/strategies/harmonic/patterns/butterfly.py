"""Butterfly: AB/XA 0.786, BC/AB 0.382-0.886, CD/BC 1.618-2.618, D extends XA 1.272-1.618"""
from strategies.harmonic.swing_detector import Pivot
from strategies.harmonic.patterns.base_pattern import BaseHarmonicPattern, PatternResult


class Butterfly(BaseHarmonicPattern):
    name = "Butterfly"

    def validate(self, x, a, b, c, d) -> PatternResult | None:
        xa = abs(a.price - x.price)
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        cd = abs(d.price - c.price)
        if xa < 1e-10 or ab < 1e-10 or bc < 1e-10: return None

        ab_xa = ab / xa
        bc_ab = bc / ab
        cd_bc = cd / bc if bc > 1e-10 else 0.0
        # D extends XA (beyond A): ratio = abs(D-X)/XA
        d_xa_ext = abs(d.price - x.price) / xa

        if not self._ratio_in_range(ab_xa, 0.786, 0.786): return None
        if not self._ratio_in_range(bc_ab, 0.382, 0.886): return None
        if not self._ratio_in_range(cd_bc, 1.618, 2.618): return None
        if not self._ratio_in_range(d_xa_ext, 1.272, 1.618): return None

        direction = "bullish" if x.type == "high" else "bearish"
        accuracy = (self._ratio_accuracy_score(ab_xa, 0.786) +
                    self._ratio_accuracy_score(bc_ab, 0.382) +
                    self._ratio_accuracy_score(cd_bc, 1.618) +
                    self._ratio_accuracy_score(d_xa_ext, 1.272)) / 4.0
        return PatternResult(
            pattern_name=self.name, direction=direction,
            points={"X": x, "A": a, "B": b, "C": c, "D": d},
            ratios={"AB/XA": ab_xa, "BC/AB": bc_ab, "CD/BC": cd_bc, "D/XA_ext": d_xa_ext},
            expected_ratios={"AB/XA": (0.786, 0.786), "BC/AB": (0.382, 0.886),
                             "CD/BC": (1.618, 2.618), "D/XA_ext": (1.272, 1.618)},
            ratio_accuracy=accuracy, prz_high=d.price * 1.001, prz_low=d.price * 0.999,
        )
