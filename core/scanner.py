import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import pytz
from core.logger import setup_system_logger

log = setup_system_logger("ForexScanner")

# Dedicated Forex watchlist
FOREX_MARKETS = {
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5},
    "GBPUSD": {"ticker": "GBPUSD=X", "pip_size": 0.0001, "digits": 5},
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5},
    "USDCAD": {"ticker": "USDCAD=X", "pip_size": 0.0001, "digits": 5},
    "USDCHF": {"ticker": "USDCHF=X", "pip_size": 0.0001, "digits": 5},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5},
    "EURJPY": {"ticker": "EURJPY=X", "pip_size": 0.01,   "digits": 3},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3},
}

class LightweightScanner:
    def __init__(self):
        self.market_map = FOREX_MARKETS
        self.cooldowns = {}
        self.cooldown_period_sec = 1800  # 30-minute cooldown per pair
        self.min_target_pips = 12.0
        
        # ACTIVE TRADING WINDOW (Sri Lanka Time / Asia/Colombo)
        # 13.5 = 1:30 PM | 21.5 = 9:30 PM
        self.tz = pytz.timezone("Asia/Colombo")
        self.window_start_hour = 13.5  # 1:30 PM SLT
        self.window_end_hour = 21.5    # 9:30 PM SLT

    def is_within_trading_window(self) -> bool:
        """Checks if current Sri Lanka time is within the designated trading window."""
        now_slt = datetime.now(self.tz)
        current_decimal_hour = now_slt.hour + (now_slt.minute / 60.0)
        return self.window_start_hour <= current_decimal_hour <= self.window_end_hour

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["High"]
        low = df["Low"]
        close = df["Close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - close).abs(),
            (low - close).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        
        plus_dm = high.diff()
        minus_dm = low.diff().abs() * -1
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
        
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=period).mean() / (atr + 1e-9))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=period).mean() / (atr + 1e-9))
        
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
        return dx.rolling(window=period).mean()

    def fetch_data(self, ticker: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            log.error(f"Error fetching {interval} data for {ticker}: {e}")
            return pd.DataFrame()

    def evaluate_pair(self, symbol: str, meta: dict) -> dict:
        ticker = meta["ticker"]

        # Fetch M15 chart
        df_m15 = self.fetch_data(ticker, interval="15m", period="5d")
        if df_m15.empty or len(df_m15) < 210:
            return None

        # Fetch H1 chart for macro trend alignment
        df_h1 = self.fetch_data(ticker, interval="1h", period="1mo")
        if df_h1.empty or len(df_h1) < 205:
            return None

        # Calculate H1 200 EMA
        df_h1["EMA200"] = df_h1["Close"].ewm(span=200, adjust=False).mean()
        h1_ema200 = float(df_h1["EMA200"].iloc[-1])
        h1_close = float(df_h1["Close"].iloc[-1])

        # Calculate M15 indicators
        df_m15["EMA200"] = df_m15["Close"].ewm(span=200, adjust=False).mean()
        df_m15["EMA50"] = df_m15["Close"].ewm(span=50, adjust=False).mean()
        df_m15["EMA20"] = df_m15["Close"].ewm(span=20, adjust=False).mean()
        df_m15["RSI"] = self.calculate_rsi(df_m15["Close"], period=14)
        df_m15["ADX"] = self.calculate_adx(df_m15, period=14)
        df_m15["ATR"] = self.calculate_atr(df_m15, period=14)

        curr = df_m15.iloc[-1]
        prev = df_m15.iloc[-2]

        price = float(curr["Close"])
        open_price = float(curr["Open"])
        low_price = float(curr["Low"])
        high_price = float(curr["High"])

        m15_ema200 = float(curr["EMA200"])
        ema50 = float(curr["EMA50"])
        ema20 = float(curr["EMA20"])
        rsi = float(curr["RSI"])
        adx_curr = float(curr["ADX"])
        adx_prev = float(prev["ADX"])
        atr = float(curr["ATR"])

        pip_size = meta["pip_size"]
        digits = meta["digits"]

        # Momentum filter (ADX >= 25 with rising slope)
        if adx_curr < 25 or adx_curr <= adx_prev or np.isnan(atr) or atr == 0:
            return None

        action = None

        # Dual MTF Alignment + Pullback to EMA20 Confirmation
        if h1_close > h1_ema200 and price > m15_ema200 and ema20 > ema50:
            if 48 <= rsi <= 65 and price > open_price:
                if abs(low_price - ema20) <= (0.6 * atr) or low_price <= ema20:
                    action = "BUY / LONG"

        elif h1_close < h1_ema200 and price < m15_ema200 and ema20 < ema50:
            if 35 <= rsi <= 52 and price < open_price:
                if abs(high_price - ema20) <= (0.6 * atr) or high_price >= ema20:
                    action = "SELL / SHORT"

        if not action:
            return None

        sl_distance = 1.5 * atr
        tp1_distance = 1.0 * atr
        tp2_distance = 1.8 * atr
        tp3_distance = 2.6 * atr

        tp1_pips = round(tp1_distance / pip_size, 1)

        # Minimum pip filter
        if tp1_pips < self.min_target_pips:
            return None

        entry_low = round(min(price, open_price), digits)
        entry_high = round(max(price, open_price), digits)
        sl_pips = round(sl_distance / pip_size, 1)

        if "BUY" in action:
            sl = round(price - sl_distance, digits)
            tp1 = round(price + tp1_distance, digits)
            tp2 = round(price + tp2_distance, digits)
            tp3 = round(price + tp3_distance, digits)
        else:
            sl = round(price + sl_distance, digits)
            tp1 = round(price - tp1_distance, digits)
            tp2 = round(price - tp2_distance, digits)
            tp3 = round(price - tp3_distance, digits)

        return {
            "symbol": symbol,
            "action": action,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "current_price": round(price, digits),
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "sl_pips": sl_pips,
            "rsi": round(rsi, 1),
            "adx": round(adx_curr, 1),
            "setup": "DUAL_MTF_PULLBACK",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }

    async def scan_all(self, bypass_cooldown: bool = False, enforce_window: bool = True) -> pd.DataFrame:
        # Check specific trading window
        if enforce_window and not self.is_within_trading_window():
            log.info("Outside of scheduled trading window (1:30 PM - 9:30 PM SLT). Scanner sleeping.")
            return pd.DataFrame()

        results = []
        now = datetime.now(timezone.utc).timestamp()

        for symbol, meta in self.market_map.items():
            if not bypass_cooldown:
                last_time = self.cooldowns.get(symbol, 0)
                if now - last_time < self.cooldown_period_sec:
                    continue

            signal = self.evaluate_pair(symbol, meta)
            if signal:
                self.cooldowns[symbol] = now
                results.append(signal)

        return pd.DataFrame(results) if results else pd.DataFrame()

    async def close(self):
        pass

Scanner = LightweightScanner