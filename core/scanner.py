import os
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import pytz
from core.logger import setup_system_logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

log = setup_system_logger("ForexScanner")

FOREX_MARKETS = {
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.0},
    "GBPUSD": {"ticker": "GBPUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.2},
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 2.0},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.0},
    "USDCAD": {"ticker": "USDCAD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.2},
    "USDCHF": {"ticker": "USDCHF=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.2},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.5},
    "EURJPY": {"ticker": "EURJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 2.5},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 3.0},
}

class LightweightScanner:
    def __init__(self):
        self.market_map = FOREX_MARKETS
        self.cooldowns = {}
        self.cooldown_period_sec = 1800
        self.min_target_pips = 12.0
        self.tz = pytz.timezone("Asia/Colombo")
        self.window_start_hour = 13.5  # 1:30 PM SLT
        self.window_end_hour = 21.5    # 9:30 PM SLT
        self.mt5_initialized = False
        self.init_mt5_terminal()

    def init_mt5_terminal(self):
        if not MT5_AVAILABLE:
            log.warning("MetaTrader5 library not installed. Defaulting to Web Data.")
            return
        if not mt5.initialize():
            log.warning(f"MT5 terminal initialization failed ({mt5.last_error()}). Defaulting to Web Data.")
            self.mt5_initialized = False
        else:
            self.mt5_initialized = True
            log.info("Live MT5 Terminal connected. Direct institutional data feed enabled.")

    def is_within_trading_window(self) -> bool:
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
        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
        return df

    def fetch_data(self, symbol: str, ticker: str, interval: str, count: int) -> pd.DataFrame:
        # Priority 1: Zero-latency MT5 Live Terminal
        if self.mt5_initialized:
            tf = mt5.TIMEFRAME_M15 if interval == "15m" else mt5.TIMEFRAME_H1
            df = self.fetch_mt5_data(symbol, tf, count)
            if not df.empty and len(df) >= 205:
                return df

        # Priority 2: Fallback to Yahoo Finance
        try:
            period = "5d" if interval == "15m" else "1mo"
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            log.error(f"Error fetching web data for {ticker}: {e}")
            return pd.DataFrame()

    def get_live_spread_pips(self, symbol: str, pip_size: float) -> float:
        if not self.mt5_initialized:
            return 1.0
        suffix = os.getenv("MT5_SYMBOL_SUFFIX", "")
        info = mt5.symbol_info(f"{symbol}{suffix}")
        if info:
            return round(info.spread * info.point / pip_size, 1)
        return 1.0

    def evaluate_pair(self, symbol: str, meta: dict) -> dict:
        ticker = meta["ticker"]
        pip_size = meta["pip_size"]
        digits = meta["digits"]

        # Spread filter: reject volatile widened spreads
        current_spread = self.get_live_spread_pips(symbol, pip_size)
        if current_spread > meta.get("max_spread_pips", 2.5):
            return None

        # Fetch M15 & H1 data
        df_m15 = self.fetch_data(symbol, ticker, "15m", 250)
        df_h1 = self.fetch_data(symbol, ticker, "1h", 250)
        if df_m15.empty or len(df_m15) < 210 or df_h1.empty or len(df_h1) < 205:
            return None

        # H1 Macro Trend
        df_h1["EMA200"] = df_h1["Close"].ewm(span=200, adjust=False).mean()
        h1_ema200 = float(df_h1["EMA200"].iloc[-1])
        h1_close = float(df_h1["Close"].iloc[-1])

        # M15 Indicators
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

        # Momentum filter: ADX >= 25 with upward slope
        if adx_curr < 25 or adx_curr <= adx_prev or np.isnan(atr) or atr == 0:
            return None

        action = None

        # Dual MTF + Pullback Rule
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

        # Spread-adjusted dynamic target parameters
        spread_allowance = current_spread * pip_size
        sl_distance = (1.5 * atr) + spread_allowance
        tp1_distance = 1.0 * atr
        tp2_distance = 1.8 * atr
        tp3_distance = 2.6 * atr

        tp1_pips = round(tp1_distance / pip_size, 1)
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

        data_source = "MT5 Live Terminal" if self.mt5_initialized else "Web Feed"

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
            "tp1_pips": tp1_pips,
            "spread_pips": current_spread,
            "rsi": round(rsi, 1),
            "adx": round(adx_curr, 1),
            "source": data_source,
            "setup": "DUAL_MTF_PULLBACK",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }

    async def scan_all(self, bypass_cooldown: bool = False, enforce_window: bool = True) -> pd.DataFrame:
        if enforce_window and not self.is_within_trading_window():
            log.info("Outside active window (1:30 PM - 9:30 PM SLT). Scanner sleeping.")
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