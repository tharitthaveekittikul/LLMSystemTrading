"""Cypher: AB/XA 0.382-0.618, BC/XA 1.272-1.414, D retraces XC 0.786"""
from strategies.harmonic.patterns.base_pattern import BaseHarmonicPattern, PatternResult


class Cypher(BaseHarmonicPattern):
    name = "Cypher"

    def validate(self, x, a, b, c, d) -> PatternResult | None:
        xa = abs(a.price - x.price)
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        xc = abs(c.price - x.price)
        if xa < 1e-10 or xc < 1e-10: return None

        ab_xa = ab / xa
        bc_xa = bc / xa if xa > 1e-10 else 0.0
        d_xc  = self._retracement_ratio(d.price, x.price, c.price)

        if not self._ratio_in_range(ab_xa, 0.382, 0.618): return None
        if not self._ratio_in_range(bc_xa, 1.272, 1.414): return None
        if not self._ratio_in_range(d_xc,  0.786, 0.786): return None

        direction = "bullish" if x.type == "high" else "bearish"
        accuracy = (self._ratio_accuracy_score(ab_xa, 0.500) +
                    self._ratio_accuracy_score(bc_xa, 1.272) +
                    self._ratio_accuracy_score(d_xc,  0.786)) / 3.0
        return PatternResult(
            pattern_name=self.name, direction=direction,
            points={"X": x, "A": a, "B": b, "C": c, "D": d},
            ratios={"AB/XA": ab_xa, "BC/XA": bc_xa, "D/XC": d_xc},
            expected_ratios={"AB/XA": (0.382, 0.618), "BC/XA": (1.272, 1.414),
                             "D/XC": (0.786, 0.786)},
            ratio_accuracy=accuracy, prz_high=d.price * 1.001, prz_low=d.price * 0.999,
        )
