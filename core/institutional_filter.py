import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from core.logger import setup_system_logger

log = setup_system_logger("InstitutionalFilter")

class InstitutionalFilterEngine:
    def __init__(self):
        self.seasonal_bias = {
            "USDJPY": {10: 1.05, 11: 1.0, 12: 0.95},
            "EURUSD": {10: 0.95, 11: 1.0, 12: 1.05},
            "BTCUSDT": {10: 1.20, 11: 1.15, 12: 1.0}
        }

    def check_news_sentiment_guard(self) -> tuple[bool, str]:
        """Simulates an NLP News Guard. Blocks trading during high-impact structural windows."""
        current_utc_hour = datetime.now(timezone.utc).hour
        # Example high-impact institutional release window simulation (e.g., US Fed / NFP hours)
        if current_utc_hour in [12, 13]:  # 12:00 - 14:00 UTC London/NY crossover major news block
            return False, "NLP News Guard: High-impact macroeconomic news window active."
        return True, "News Sentiment Clear"

    def check_volatility_regime(self, df_base: pd.DataFrame) -> str:
        if len(df_base) < 50:
            return "NORMAL"
        atr_series = (df_base["High"] - df_base["Low"]).rolling(14).mean()
        current_atr, atr_median = atr_series.iloc[-1], atr_series.median()
        if current_atr < (0.7 * atr_median):
            return "LOW_VOLATILITY_CHOP"
        elif current_atr > (1.6 * atr_median):
            return "EXPLOSIVE_BREAKOUT"
        return "NORMAL"

    def check_intermarket_correlation(self, symbol: str, direction: str) -> tuple[bool, str]:
        try:
            if symbol in ["EURUSD", "AUDUSD", "GBPUSD"]:
                dxy = yf.download("DX-Y.INI", period="5d", interval="1h", progress=False)
                if not dxy.empty:
                    if isinstance(dxy.columns, pd.MultiIndex):
                        dxy.columns = dxy.columns.get_level_values(0)
                    dxy_trend = dxy["Close"].iloc[-1] - dxy["Close"].iloc[-5]
                    if direction == "BUY" and dxy_trend > 0:
                        return False, "Intermarket Conflict: DXY is bullish against EURUSD buy"
                    if direction == "SELL" and dxy_trend < 0:
                        return False, "Intermarket Conflict: DXY is bearish against EURUSD sell"
        except Exception:
            pass
        return True, "Passed Correlation"

    def evaluate_institutional_confluence(self, symbol: str, direction: str, df_base: pd.DataFrame) -> tuple[bool, str, dict]:
        news_ok, news_reason = self.check_news_sentiment_guard()
        if not news_ok:
            return False, news_reason, {}

        regime = self.check_volatility_regime(df_base)
        if regime == "LOW_VOLATILITY_CHOP":
            return False, "Blocked by Low Volatility Chop Regime", {}

        corr_passed, corr_reason = self.check_intermarket_correlation(symbol, direction)
        if not corr_passed:
            return False, corr_reason, {}

        current_month = datetime.now(timezone.utc).month
        season_multiplier = self.seasonal_bias.get(symbol, {}).get(current_month, 1.0)

        meta = {"volatility_regime": regime, "seasonal_multiplier": season_multiplier}
        return True, "Passed Institutional Confluence", meta