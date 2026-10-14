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

log = setup_system_logger("MultiTimeframeScanner")

# Liquid Forex majors and crosses
FOREX_MARKETS = {
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.2},
    "GBPUSD": {"ticker": "GBPUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.5},
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 2.2},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.2},
    "USDCAD": {"ticker": "USDCAD=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.5},
    "USDCHF": {"ticker": "USDCHF=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.5},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5, "max_spread_pips": 2.5},
    "EURJPY": {"ticker": "EURJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 2.8},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread_pips": 3.2},
}

TIMEFRAME_CONFIG = {
    "5m": {
        "macro_tf": "15m",
        "adx_threshold": 22.0,
        "min_pips": 8.0,
        "sl_mult": 1.4,
        "tp1_mult": 1.2,
        "tp2_mult": 2.0,
        "tp3_mult": 2.8,
        "desc": "FAST SCALP"
    },
    "15m": {
        "macro_tf": "1h",
        "adx_threshold": 24.0,
        "min_pips": 12.0,
        "sl_mult": 1.5,
        "tp1_mult": 1.5,
        "tp2_mult": 2.2,
        "tp3_mult": 3.0,
        "desc": "INTRADAY SWING"
    },
    "1h": {
        "macro_tf": "1d",
        "adx_threshold": 25.0,
        "min_pips": 22.0,
        "sl_mult": 1.8,
        "tp1_mult": 2.0,
        "tp2_mult": 3.0,
        "tp3_mult": 4.0,
        "desc": "MACRO TREND"
    }
}

class LightweightScanner:
    def __init__(self):
        self.market_map = FOREX_MARKETS
        self.cooldowns = {}
        self.cooldown_period_sec = 1200  # 20-minute anti-spam cooldown per symbol/timeframe
        self.mt5_initialized = False
        self.init_mt5_terminal()

    def init_mt5_terminal(self):
        if not MT5_AVAILABLE:
            return
        if mt5.initialize():
            self.mt5_initialized = True
            log.info("Live MT5 Terminal connected. Direct institutional data feed enabled.")
        else:
            self.mt5_initialized = False

    def is_within_trading_window(self) -> bool:
        """24/5 Trading: Active Monday through Friday, closed over weekends."""
        weekday = datetime.now(timezone.utc).weekday()
        return weekday < 5

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

    def fetch_mt5_data(self, symbol: str, interval: str, count: int) -> pd.DataFrame:
        if not self.mt5_initialized:
            return pd.DataFrame()
        tf_map = {
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "1h": mt5.TIMEFRAME_H1,
            "1d": mt5.TIMEFRAME_D1
        }
        tf = tf_map.get(interval)
        if tf is None:
            return pd.DataFrame()

        suffix = os.getenv("MT5_SYMBOL_SUFFIX", "")
        broker_symbol = f"{symbol}{suffix}"
        mt5.symbol_select(broker_symbol, True)
        rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
        return df

    def fetch_data(self, symbol: str, ticker: str, interval: str, count: int) -> pd.DataFrame:
        if self.mt5_initialized:
            df = self.fetch_mt5_data(symbol, interval, count)
            if not df.empty and len(df) >= 120:
                return df

        # Fallback to Yahoo Finance
        period_map = {"5m": "5d", "15m": "1mo", "1h": "3mo", "1d": "1y"}
        period = period_map.get(interval, "1mo")
        try:
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

    def evaluate_timeframe(self, symbol: str, meta: dict, tf: str) -> dict:
        cfg = TIMEFRAME_CONFIG[tf]
        macro_tf = cfg["macro_tf"]
        ticker = meta["ticker"]
        pip_size = meta["pip_size"]
        digits = meta["digits"]

        # Spread Guard
        current_spread = self.get_live_spread_pips(symbol, pip_size)
        if current_spread > meta.get("max_spread_pips", 3.0):
            return None

        # Fetch base timeframe and higher macro timeframe
        df_base = self.fetch_data(symbol, ticker, tf, 220)
        df_macro = self.fetch_data(symbol, ticker, macro_tf, 220)

        if df_base.empty or len(df_base) < 150 or df_macro.empty or len(df_macro) < 120:
            return None

        # Macro Trend Indicator
        df_macro["EMA200"] = df_macro["Close"].ewm(span=min(200, len(df_macro)-5), adjust=False).mean()
        macro_ema200 = float(df_macro["EMA200"].iloc[-1])
        macro_close = float(df_macro["Close"].iloc[-1])

        # Base Timeframe Indicators
        df_base["EMA200"] = df_base["Close"].ewm(span=min(200, len(df_base)-5), adjust=False).mean()
        df_base["EMA50"] = df_base["Close"].ewm(span=50, adjust=False).mean()
        df_base["EMA20"] = df_base["Close"].ewm(span=20, adjust=False).mean()
        df_base["RSI"] = self.calculate_rsi(df_base["Close"], period=14)
        df_base["ADX"] = self.calculate_adx(df_base, period=14)
        df_base["ATR"] = self.calculate_atr(df_base, period=14)

        curr = df_base.iloc[-1]
        prev = df_base.iloc[-2]

        price = float(curr["Close"])
        open_price = float(curr["Open"])
        low_price = float(curr["Low"])
        high_price = float(curr["High"])

        base_ema200 = float(curr["EMA200"])
        ema50 = float(curr["EMA50"])
        ema20 = float(curr["EMA20"])
        rsi = float(curr["RSI"])
        adx_curr = float(curr["ADX"])
        adx_prev = float(prev["ADX"])
        atr = float(curr["ATR"])

        # Momentum threshold check
        if adx_curr < cfg["adx_threshold"] or np.isnan(atr) or atr == 0:
            return None

        action = None

        # Bullish Multi-Timeframe Alignment
        if macro_close > macro_ema200 and price > base_ema200 and ema20 > ema50:
            if 46 <= rsi <= 68 and price > open_price:
                if abs(low_price - ema20) <= (0.75 * atr) or low_price <= ema20:
                    action = "BUY / LONG"

        # Bearish Multi-Timeframe Alignment
        elif macro_close < macro_ema200 and price < base_ema200 and ema20 < ema50:
            if 32 <= rsi <= 54 and price < open_price:
                if abs(high_price - ema20) <= (0.75 * atr) or high_price >= ema20:
                    action = "SELL / SHORT"

        if not action:
            return None

        # Risk-reward and spread buffer calculations
        spread_allowance = current_spread * pip_size
        sl_distance = (cfg["sl_mult"] * atr) + spread_allowance
        tp1_distance = cfg["tp1_mult"] * atr
        tp2_distance = cfg["tp2_mult"] * atr
        tp3_distance = cfg["tp3_mult"] * atr

        tp1_pips = round(tp1_distance / pip_size, 1)
        if tp1_pips < cfg["min_pips"]:
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

        source_name = "Live MT5" if self.mt5_initialized else "Web Feed"

        return {
            "symbol": symbol,
            "timeframe": tf,
            "strategy_type": cfg["desc"],
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
            "source": source_name,
            "setup": f"{tf.upper()} {cfg['desc']}",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }

    async def scan_all(self, bypass_cooldown: bool = False, enforce_window: bool = True) -> pd.DataFrame:
        if enforce_window and not self.is_within_trading_window():
            log.info("Weekend markets closed. Scanner sleeping.")
            return pd.DataFrame()

        results = []
        now = datetime.now(timezone.utc).timestamp()

        # Iterate across all pairs and enabled timeframes (5m, 15m, 1h)
        for symbol, meta in self.market_map.items():
            for tf in ["5m", "15m", "1h"]:
                cooldown_key = f"{symbol}_{tf}"
                if not bypass_cooldown:
                    last_time = self.cooldowns.get(cooldown_key, 0)
                    if now - last_time < self.cooldown_period_sec:
                        continue

                signal = self.evaluate_timeframe(symbol, meta, tf)
                if signal:
                    self.cooldowns[cooldown_key] = now
                    results.append(signal)

        return pd.DataFrame(results) if results else pd.DataFrame()

    async def close(self):
        if self.mt5_initialized:
            try:
                mt5.shutdown()
            except Exception:
                pass

Scanner = LightweightScanner