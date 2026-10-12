import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from core.logger import setup_system_logger

log = setup_system_logger("ForexScanner")

# Dedicated Forex watchlist (Liquid majors and crosses with tight spreads)
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
        self.cooldowns = {}  # {symbol: timestamp}
        self.cooldown_period_sec = 1800  # 30-minute cooldown per pair

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

    def fetch_data(self, ticker: str) -> pd.DataFrame:
        try:
            df = yf.download(ticker, period="5d", interval="15m", progress=False)
            if df.empty or len(df) < 210:
                return pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            return df
        except Exception as e:
            log.error(f"Error fetching data for {ticker}: {e}")
            return pd.DataFrame()

    def evaluate_pair(self, symbol: str, meta: dict) -> dict:
        ticker = meta["ticker"]
        df = self.fetch_data(ticker)
        if df.empty:
            return None

        # Indicator Calculations
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["RSI"] = self.calculate_rsi(df["Close"], period=14)
        df["ADX"] = self.calculate_adx(df, period=14)
        df["ATR"] = self.calculate_atr(df, period=14)

        current = df.iloc[-1]
        price = float(current["Close"])
        ema200 = float(current["EMA200"])
        ema50 = float(current["EMA50"])
        ema20 = float(current["EMA20"])
        rsi = float(current["RSI"])
        adx = float(current["ADX"])
        atr = float(current["ATR"])

        pip_size = meta["pip_size"]
        digits = meta["digits"]

        # Trend & Momentum Rules:
        # ADX >= 20 confirms active trend momentum
        if adx < 20 or np.isnan(atr) or atr == 0:
            return None

        action = None
        setup_type = "TREND_CONTINUATION"

        if price > ema200 and ema20 > ema50 and 45 <= rsi <= 68:
            if current["Close"] > current["Open"]:
                action = "BUY / LONG"

        elif price < ema200 and ema20 < ema50 and 32 <= rsi <= 55:
            if current["Close"] < current["Open"]:
                action = "SELL / SHORT"

        if not action:
            return None

        # Volatility-Based Stop Loss and 3-Tier Targets
        sl_distance = 1.5 * atr
        tp1_distance = 1.0 * atr
        tp2_distance = 1.8 * atr
        tp3_distance = 2.6 * atr

        entry_low = round(min(price, float(current["Open"])), digits)
        entry_high = round(max(price, float(current["Open"])), digits)

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

        sl_pips = round(sl_distance / pip_size, 1)

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
            "adx": round(adx, 1),
            "setup": setup_type,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }

    async def scan_all(self, bypass_cooldown: bool = False) -> pd.DataFrame:
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

        if results:
            log.info(f"Scan complete. Discovered {len(results)} Forex setups.")
            return pd.DataFrame(results)

        log.info("Scan complete. No high-probability Forex setups identified.")
        return pd.DataFrame()

    async def close(self):
        """Cleanup handler if needed by external async loops."""
        pass

# Aliases to guarantee compatibility with all imports
Scanner = LightweightScanner