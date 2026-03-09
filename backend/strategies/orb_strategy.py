from __future__ import annotations
from datetime import datetime, time, timezone
import zoneinfo

from strategies.base_strategy import RuleOnlyStrategy, StrategyResult
from services.mtf_data import MTFMarketData

class ORBStrategy(RuleOnlyStrategy):
    """Type 3 Strategy: Opening Range Breakout (ORB) with FVG confirmation.

    Requirements:
    1. Define Trading Range: 5-minute candle between 9:30 AM and 9:35 AM NY time. Mark High/Low.
    2. Confirm Breakout: Move beyond High/Low on 1-minute chart, confirmed by FVG.
       - FVG: 3-candle pattern with gap between wick of 1st and 3rd candle.
    3. Trade Entry: Execute when FVG confirms the break.
       - Stop Loss: Low/High of 1st candle of FVG.
       - Take Profit: 3:1 RR fixed.
    4. Limits: 1 trade or no trade per day.
    """
    
    primary_tf: str = "M1"
    context_tfs: tuple[str, ...] = ("M5",)
    
    # State tracking for 1 trade per day
    last_traded_date: str | None = None
    
    ny_tz = zoneinfo.ZoneInfo("America/New_York")
    
    def _convert_to_ny_time(self, dt: datetime) -> datetime:
        """Convert a UTC datetime to New York time."""
        if dt.tzinfo is None:
            # Assume naive datetime is UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self.ny_tz)

    def check_rule(self, market_data: "MTFMarketData") -> StrategyResult | None:
        current_dt = self._convert_to_ny_time(market_data.trigger_time)
        current_date_str = current_dt.strftime("%Y-%m-%d")
        
        # Rule: 1 trade or no trade per day only
        if self.last_traded_date == current_date_str:
            return None
            
        ny_time = current_dt.time()
        
        # Only start looking for a breakout after 9:35 NY Time (when 9:30-9:35 candle closes)
        if ny_time < time(9, 35):
            return None

        # 1. Identify 5-minute opening range
        m5_data = market_data.timeframes.get("M5")
        if not m5_data or not m5_data.candles:
            return None
            
        orb_high = None
        orb_low = None
        
        # Search backwards for the 9:30 AM candle on the current day
        for candle in reversed(m5_data.candles):
            c_dt = self._convert_to_ny_time(candle.time)
            
            if c_dt.date() < current_dt.date():
                break # We went past today, stop searching
                
            if c_dt.time() == time(9, 30):
                orb_high = candle.high
                orb_low = candle.low
                break
                
        if orb_high is None or orb_low is None:
            return None

        # 2. Identify FVG and Breakout on 1-minute chart
        m1_data = market_data.timeframes.get("M1")
        if not m1_data or len(m1_data.candles) < 3:
            return None
            
        c1 = m1_data.candles[-3]
        c2 = m1_data.candles[-2]
        c3 = m1_data.candles[-1]
        
        entry_price = c3.close 
        
        # Bullish FVG & Breakout 
        bullish_fvg = c1.high < c3.low
        bullish_break = entry_price > orb_high
        
        if bullish_fvg and bullish_break:
            stop_loss = c1.low
            if stop_loss >= entry_price:
                return None
                
            risk = entry_price - stop_loss
            take_profit = entry_price + (risk * 3)
            
            self.last_traded_date = current_date_str
            
            return StrategyResult(
                action="BUY",
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.9,
                rationale="Bullish FVG confirmed breakout of 9:30 AM ORB High.",
                timeframe=self.primary_tf,
                pattern_name="ORB_Bullish_FVG"
            )
            
        # Bearish FVG & Breakout
        bearish_fvg = c1.low > c3.high
        bearish_break = entry_price < orb_low
        
        if bearish_fvg and bearish_break:
            stop_loss = c1.high
            if stop_loss <= entry_price:
                return None
                
            risk = stop_loss - entry_price
            take_profit = entry_price - (risk * 3)
            
            self.last_traded_date = current_date_str
            
            return StrategyResult(
                action="SELL",
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.9,
                rationale="Bearish FVG confirmed breakout of 9:30 AM ORB Low.",
                timeframe=self.primary_tf,
                pattern_name="ORB_Bearish_FVG"
            )

        return None
