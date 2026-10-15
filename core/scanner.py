import os
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from core.logger import setup_system_logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

log = setup_system_logger("ForexScanner")

# HIGH-EXPECTANCY PAIRS ONLY
# Removed EURJPY, USDCAD, and USDCHF based on week 41 MT5 report analysis
FOREX_MARKETS = {
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 1.8},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.0},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 1.8},
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 1.8},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 2.6},
}

class LightweightScanner:
    def __init__(self):
        self.market_map = FOREX_MARKETS
        self.cooldowns = {}
        self.cooldown_period_sec = 2400  # 40-minute cooldown to prevent immediate revenge entries
        self.min_target_pips = 16.0      # Enforce healthy minimum profit size
        self.mt5_initialized = False
        self.init_mt5_terminal()

    def init_mt5_terminal(self):
        if not MT5_AVAILABLE:
            return
        if mt5.initialize():
            self.mt5_initialized = True
            log.info("Live MT5 Terminal connected. Direct institutional data feed active.")
        else:
            self.mt5_initialized = False

    def is_within_trading_window(self) -> bool:
        """24/5 continuous trading, avoiding weekend spreads."""
        return datetime.now(timezone.utc).weekday() < 5

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

    def fetch_mt5_data(self, symbol: str, timeframe, count: int) -> pd.DataFrame:
        if not self.mt5_initialized:
            return pd.DataFrame()
        suffix = os.getenv("MT5_SYMBOL_SUFFIX", "")
        broker_symbol = f"{symbol}{suffix}"
        mt5.symbol_select(broker_symbol, True)
        rates = mt5.copy_rates_from_pos(broker_symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "tick_volume": "Volume"}, inplace=True)
        return df

    def fetch_data(self, symbol: str, ticker: str, interval: str, count: int) -> pd.DataFrame:
        if self.mt5_initialized:
            tf = mt5.TIMEFRAME_M15 if interval == "15m" else mt5.TIMEFRAME_H1
            df = self.fetch_mt5_data(symbol, tf, count)
            if not df.empty and len(df) >= 205:
                return df

        try:
            period = "5d" if interval == "15m" else "1mo"
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            log.error(f"Data fetch error ({ticker} - {interval}): {e}")
            return pd.DataFrame()

    def get_live_spread_pips(self, symbol: str, pip_size: float) -> float:
        if not self.mt5_initialized:
            return 1.2
        suffix = os.getenv("MT5_SYMBOL_SUFFIX", "")
        info = mt5.symbol_info(f"{symbol}{suffix}")
        if info:
            return round(info.spread * info.point / pip_size, 1)
        return 1.2

    def evaluate_pair(self, symbol: str, meta: dict) -> dict:
        ticker = meta["ticker"]
        pip_size = meta["pip_size"]
        digits = meta["digits"]

        current_spread = self.get_live_spread_pips(symbol, pip_size)
        if current_spread > meta.get("max_spread_pips", 2.0):
            return None

        df_m15 = self.fetch_data(symbol, ticker, "15m", 250)
        df_h1 = self.fetch_data(symbol, ticker, "1h", 250)
        if df_m15.empty or len(df_m15) < 210 or df_h1.empty or len(df_h1) < 205:
            return None

        # 1. Macro Trend: H1 200 EMA + 50 EMA Slope
        df_h1["EMA200"] = df_h1["Close"].ewm(span=200, adjust=False).mean()
        df_h1["EMA50"] = df_h1["Close"].ewm(span=50, adjust=False).mean()
        h1_ema200 = float(df_h1["EMA200"].iloc[-1])
        h1_ema50 = float(df_h1["EMA50"].iloc[-1])
        h1_close = float(df_h1["Close"].iloc[-1])

        # 2. M15 Indicators
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

        # Stricter momentum threshold: require sustained trend
        if adx_curr < 25.0 or adx_curr < adx_prev or np.isnan(atr) or atr == 0:
            return None

        # Candlestick Anatomy
        body_size = abs(price - open_price)
        candle_range = max(high_price - low_price, 1e-9)
        lower_wick = min(open_price, price) - low_price
        upper_wick = high_price - max(open_price, price)

        action = None

        # BUY: Confirmed Uptrend on H1 & M15 + Rejection of EMA 20
        if h1_close > h1_ema200 and h1_ema50 > h1_ema200 and price > m15_ema200 and ema20 > ema50:
            if 50 <= rsi <= 65 and price > open_price:
                if abs(low_price - ema20) <= (0.5 * atr) or low_price <= ema20:
                    if lower_wick >= (0.30 * candle_range) or body_size >= (0.55 * candle_range):
                        action = "BUY"

        # SELL: Confirmed Downtrend on H1 & M15 + Rejection of EMA 20
        elif h1_close < h1_ema200 and h1_ema50 < h1_ema200 and price < m15_ema200 and ema20 < ema50:
            if 35 <= rsi <= 50 and price < open_price:
                if abs(high_price - ema20) <= (0.5 * atr) or high_price >= ema20:
                    if upper_wick >= (0.30 * candle_range) or body_size >= (0.55 * candle_range):
                        action = "SELL"

        if not action:
            return None

        # 3. Mathematical Edge: 1 : 1.33 Risk-to-Reward
        # SL = 1.2 * ATR (Tighter risk) | TP = 1.6 * ATR (Larger payoff)
        sl_distance = 1.2 * atr
        tp_distance = 1.6 * atr

        sl_pips = round(sl_distance / pip_size, 1)
        tp_pips = round(tp_distance / pip_size, 1)

        if tp_pips < self.min_target_pips:
            return None

        entry_low = round(min(price, open_price), digits)
        entry_high = round(max(price, open_price), digits)

        if action == "BUY":
            sl = round(price - sl_distance, digits)
            tp = round(price + tp_distance, digits)
        else:
            sl = round(price + sl_distance, digits)
            tp = round(price - tp_distance, digits)

        source_name = "Live MT5" if self.mt5_initialized else "Web Feed"

        return {
            "symbol": symbol,
            "action": action,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "current_price": round(price, digits),
            "sl": sl,
            "tp": tp,
            "tp1": tp,
            "tp2": round(price + (2.4 * atr) if action == "BUY" else price - (2.4 * atr), digits),
            "tp3": round(price + (3.2 * atr) if action == "BUY" else price - (3.2 * atr), digits),
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "risk_reward": "1:1.33",
            "spread_pips": current_spread,
            "rsi": round(rsi, 1),
            "adx": round(adx_curr, 1),
            "source": source_name,
            "setup": "H1_M15_ASYMMETRIC_REJECTION",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }

    async def scan_all(self, bypass_cooldown: bool = False, enforce_window: bool = True) -> pd.DataFrame:
        if enforce_window and not self.is_within_trading_window():
            log.info("Weekend rollover. Scanner standby.")
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
        if self.mt5_initialized:
            try:
                mt5.shutdown()
            except Exception:
                pass

Scanner = LightweightScanner