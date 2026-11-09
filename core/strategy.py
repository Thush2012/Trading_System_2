import numpy as np
import pandas as pd


class StrategyEngine:
    def __init__(
        self,
        fast_ema: int = 9,
        slow_ema: int = 21,
        trend_ema: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
        adx_period: int = 14
    ):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.trend_ema = trend_ema
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.adx_period = adx_period

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 1. Exponential Moving Averages (Trend & Trigger)
        df["ema_fast"] = df["close"].ewm(span=self.fast_ema, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_ema, adjust=False).mean()
        df["ema_trend"] = df["close"].ewm(span=self.trend_ema, adjust=False).mean()

        # 2. RSI (Momentum Filter)
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        # 3. Average True Range (Dynamic Volatility)
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        # 4. ADX (Directional Trend Strength Filter - Eliminates Range Whipsaws)
        up_move = df["high"] - df["high"].shift(1)
        down_move = df["low"].shift(1) - df["low"]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr_smooth = tr.rolling(window=self.adx_period).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=self.adx_period).mean() / tr_smooth.replace(0, np.nan))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=self.adx_period).mean() / tr_smooth.replace(0, np.nan))
        
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df["adx"] = dx.rolling(window=self.adx_period).mean().fillna(0)

        return df

    def generate_signals(
        self,
        df: pd.DataFrame,
        risk_reward_ratio: float = 2.0,
        macro_bias: str = "ANY"
    ) -> pd.DataFrame:
        df = self.calculate_indicators(df)
        df["signal"] = 0
        df["action"] = "⚪ NEUTRAL"
        df["entry_price"] = np.nan
        df["stop_loss"] = np.nan
        df["take_profit"] = np.nan

        # High-Confluence Condition 1: Market must be in an active trend (ADX > 22)
        is_trending = df["adx"] > 22.0

        # High-Confluence Condition 2: Clear Crossover with Momentum & Dynamic Spread
        buy_cond = (
            is_trending &
            (df["ema_fast"] > df["ema_slow"]) &
            (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1)) &
            (df["rsi"] >= 52) & (df["rsi"] <= 68) # Clean momentum window (avoids exhausted overbought)
        )

        sell_cond = (
            is_trending &
            (df["ema_fast"] < df["ema_slow"]) &
            (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1)) &
            (df["rsi"] <= 48) & (df["rsi"] >= 32) # Clean momentum window (avoids oversold extremes)
        )

        for i in range(len(df)):
            current_close = df.loc[i, "close"]
            current_atr = df.loc[i, "atr"]

            if pd.isna(current_atr) or current_atr == 0:
                current_atr = current_close * 0.002

            # Long entry aligned with 4H bullish bias
            if buy_cond.iloc[i] and macro_bias in ["BULLISH", "ANY"]:
                df.loc[i, "signal"] = 1
                df.loc[i, "action"] = "🟢 BUY"
                df.loc[i, "entry_price"] = current_close
                df.loc[i, "stop_loss"] = round(current_close - (1.5 * current_atr), 5)
                df.loc[i, "take_profit"] = round(current_close + (1.5 * risk_reward_ratio * current_atr), 5)

            # Short entry aligned with 4H bearish bias
            elif sell_cond.iloc[i] and macro_bias in ["BEARISH", "ANY"]:
                df.loc[i, "signal"] = -1
                df.loc[i, "action"] = "🔴 SELL"
                df.loc[i, "entry_price"] = current_close
                df.loc[i, "stop_loss"] = round(current_close + (1.5 * current_atr), 5)
                df.loc[i, "take_profit"] = round(current_close - (1.5 * risk_reward_ratio * current_atr), 5)

        return df