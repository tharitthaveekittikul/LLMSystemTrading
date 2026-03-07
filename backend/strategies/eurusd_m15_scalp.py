from strategies.base import BaseStrategy


class EURUSDScalp(BaseStrategy):
    """
    M15 scalping strategy for EURUSD and GBPUSD.

    Focuses on London open momentum with RSI divergence + EMA crossover confluence.
    Tight stops, conservative sizing.

    To use: register in the UI with
        module_path = "strategies.eurusd_m15_scalp"
        class_name  = "EURUSDScalp"
    """

    symbols = ["EURUSD", "GBPUSD"]
    timeframe = "M15"
    trigger_type = "candle_close"

    def system_prompt(self) -> str:
        return (
            "You are a scalping specialist on the M15 timeframe.\n"
            "Focus on momentum trades during the London open session (07:00-09:00 UTC).\n"
            "Only enter when RSI divergence AND a 9/21 EMA crossover align.\n"
            "Keep stops tight: maximum 15 pips. Risk 0.5% of account per trade.\n"
            "Outside London open hours, prefer HOLD unless confidence exceeds 0.90."
        )

    def lot_size(self) -> float:
        return 0.05

    def sl_pips(self) -> float:
        return 15
