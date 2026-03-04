import pandas as pd
import numpy as np
from datetime import datetime, time, UTC
import pytz

from strategies.base_strategy import BaseStrategy


class EmaAtrBreakout(BaseStrategy):
    """
    Multi-Timeframe EMA & ATR Breakout Strategy
    
    Rule 1 (Trend): 200 EMA setup.
    Rule 2 (Trigger): 14 RSI crossover setup.
    Rule 3 (Exits): ATR-based dynamic stops.
    
    Notes: symbols and timeframe should be dynamically assigned via the DB.
    """
    symbols = []
    timeframe = "H1"

    def _calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _calculate_rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.rolling(window=period).mean()

    def generate_signal(self, market_data: dict) -> dict | None:
        symbol = market_data.get("symbol", "")
        tf = market_data.get("timeframe", self.timeframe)
        current_price = market_data.get("current_price", 0.0)
        candles = market_data.get("candles", [])

        if len(candles) < 200:
            return self._hold_signal(f"Not enough data for 200 EMA (got {len(candles)})", current_price, tf)

        df = pd.DataFrame(candles)
        
        # Calculate indicators
        df['ema_200'] = self._calculate_ema(df['close'], 200)
        df['rsi_14'] = self._calculate_rsi(df['close'], 14)
        df['atr_14'] = self._calculate_atr(df, 14)

        current_ema = df['ema_200'].iloc[-1]
        current_atr = df['atr_14'].iloc[-1]
        
        last_rsi = df['rsi_14'].iloc[-2]
        current_rsi = df['rsi_14'].iloc[-1]

        # Time filter for GBPJPY (07:00-09:00 UTC)
        if "GBPJPY" in symbol:
            try:
                # MT5 times are usually broker time, but let's assume UTC or get it from candle time
                # 'time' key from mt5 bridge is a unix timestamp
                candle_time = datetime.fromtimestamp(candles[-1]['time'], tz=UTC)
                if time(7, 0) <= candle_time.time() <= time(9, 0):
                    return self._hold_signal("GBPJPY time filter (07:00-09:00 UTC)", current_price, tf)
            except Exception:
                pass # fallback if time parsing fails

        # RSI filter for AUDUSD (45-55)
        if "AUDUSD" in symbol:
            if 45 <= current_rsi <= 55:
                return self._hold_signal(f"AUDUSD RSI filter ({current_rsi:.2f} in 45-55)", current_price, tf)

        # Long Condition
        # Rule 1: Price > 200 EMA
        # Rule 2: RSI dips below 40 then crosses above 40
        long_setup = current_price > current_ema and \
                     last_rsi < 40 and current_rsi > 40

        # Short Condition
        # Rule 1: Price < 200 EMA
        # Rule 2: RSI rises above 60 then crosses below 60
        short_setup = current_price < current_ema and \
                      last_rsi > 60 and current_rsi < 60

        action = "HOLD"
        rationale = "No clear EMA/RSI breakout setup"
        confidence = 0.0
        sl = 0.0
        tp = 0.0

        if long_setup:
            action = "BUY"
            rationale = f"Price > 200 EMA ({current_ema:.5f}), RSI ({last_rsi:.1f} -> {current_rsi:.1f}) crossed > 40."
            confidence = 0.90
            sl = current_price - (1.5 * current_atr)
            tp = current_price + (3.0 * current_atr)
        elif short_setup:
            action = "SELL"
            rationale = f"Price < 200 EMA ({current_ema:.5f}), RSI ({last_rsi:.1f} -> {current_rsi:.1f}) crossed < 60."
            confidence = 0.90
            sl = current_price + (1.5 * current_atr)
            tp = current_price - (3.0 * current_atr)

        if action == "HOLD":
            return self._hold_signal(rationale, current_price, tf)

        return {
            "action": action,
            "entry": current_price,
            "stop_loss": round(sl, 5),
            "take_profit": round(tp, 5),
            "confidence": confidence,
            "rationale": rationale,
            "timeframe": tf,
        }

    def _hold_signal(self, rationale: str, current_price: float, tf: str) -> dict:
        return {
            "action": "HOLD",
            "entry": current_price,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "confidence": 1.0,
            "rationale": rationale,
            "timeframe": tf,
        }
