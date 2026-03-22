"""Strategy Registry — central catalogue of all available rule-based strategies.

Each entry declares:
  - display_name / description  (shown in UI)
  - module_path + class_name    (used by the engine to instantiate)
  - execution_mode              (auto-set from the class)
  - params                      (schema for dynamic config UI)

Adding a new strategy:
  1. Create the class in backend/strategies/<your_module>.py
  2. Add a StrategyMeta entry to REGISTRY below
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ParamField:
    """Describes one configurable parameter for the UI form."""
    name: str
    label: str
    type: Literal["int", "float", "bool", "str", "select"]
    default: Any
    description: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None   # only for type="select"

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "description": self.description,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.step is not None:
            d["step"] = self.step
        if self.options is not None:
            d["options"] = self.options
        return d


@dataclass
class StrategyMeta:
    """Metadata for one registered strategy class."""
    key: str
    display_name: str
    description: str
    execution_mode: str
    module_path: str
    class_name: str
    params: list[ParamField] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "params": [p.to_dict() for p in self.params],
        }


# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, StrategyMeta] = {
    "harmonic": StrategyMeta(
        key="harmonic",
        display_name="Harmonic Patterns",
        description=(
            "Williams Fractals swing detection + 7 classic harmonic patterns "
            "(Gartley, Bat, Butterfly, Crab, Shark, Cypher, ABCD). "
            "Entry at PRZ with ATR-based SL/TP. Zero LLM cost."
        ),
        execution_mode="rule_only",
        module_path="strategies.harmonic.harmonic_strategy",
        class_name="HarmonicStrategy",
        params=[
            ParamField(
                name="fractal_n",
                label="Fractal N",
                type="int",
                default=2,
                min=1,
                max=10,
                description="Confirmation candles each side for Williams Fractals pivot detection.",
            ),
            ParamField(
                name="min_pattern_pips",
                label="Min Pattern Pips",
                type="float",
                default=0.0,
                min=0.0,
                step=1.0,
                description="Minimum XA leg size in pips (0 = no filter).",
            ),
            ParamField(
                name="prz_cooldown_candles",
                label="PRZ Cooldown (candles)",
                type="int",
                default=20,
                min=0,
                max=200,
                description="Suppress re-entry into the same PRZ for this many primary-TF candles.",
            ),
            ParamField(
                name="prz_tolerance_pct",
                label="PRZ Tolerance %",
                type="float",
                default=0.005,
                min=0.001,
                max=0.05,
                step=0.001,
                description="Price distance threshold to consider two entries in the same PRZ (0.5% default).",
            ),
        ],
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_strategies() -> list[dict]:
    """Return all registered strategies as plain dicts (for the API)."""
    return [meta.to_dict() for meta in REGISTRY.values()]


def get_strategy(key: str) -> StrategyMeta | None:
    return REGISTRY.get(key)
