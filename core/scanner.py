import os
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import pytz
from core.logger import setup_system_logger
from core.loss_memory import LossMemoryEngine

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

log = setup_system_logger("CloudAnalyzer")
memory_guard = LossMemoryEngine()

FOREX_MARKETS = {
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread": 1.8},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5, "max_spread": 2.0},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread": 1.8},
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread": 1.8},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread": 2.6},
}

class LightweightScanner:
    def __init__(self):
        self.market_map = FOREX_MARKETS
        self.cooldowns = {}
        self.cooldown_sec = 2400
        self.min_tp_pips = 15.0
        self.slt_tz = pytz.timezone("Asia/Colombo")
        self.start_hour = 13.5  # 1:30 PM SLT
        self.end_hour = 21.5    # 9:30 PM SLT
        self.mt5_initialized = False
        self._connect_mt5()

    def _connect_mt5(self):
        if datetime.now(self.slt_tz).weekday() >= 5:
            return
        if HAS_MT5 and mt5.initialize():
            self.mt5_initialized = True
            log.info("MT5 Live Feed active.")

    def is_within_trading_window(self) -> bool:
        now_slt = datetime.now(self.slt_tz)
        if now_slt.weekday() >= 5:
            return False
        dec_hour = now_slt.hour + (now_slt.minute / 60.0)
        return self.start_hour <= dec_hour <= self.end_hour

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l, c_prev = df["High"], df["Low"], df["Close"].shift(1)
        tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def _calc_rsi(self, s: pd.Series, period: int = 14) -> pd.Series:
        diff = s.diff()
        up = diff.where(diff > 0, 0.0).rolling(window=period).mean()
        dn = (-diff.where(diff < 0, 0.0)).rolling(window=period).mean()
        rs = up / (dn + 1e-9)
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l = df["High"], df["Low"]
        up_move = h.diff()
        dn_move = l.diff().abs() * -1.0
        plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
        atr = self._calc_atr(df, period)
        p_di = 100.0 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / (atr + 1e-9))
        m_di = 100.0 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / (atr + 1e-9))
        dx = 100.0 * (p_di - m_di).abs() / (p_di + m_di + 1e-9)
        return dx.rolling(window=period).mean()

    def _get_candles(self, symbol: str, ticker: str, tf: str) -> pd.DataFrame:
        if self.mt5_initialized and datetime.now(self.slt_tz).weekday() < 5:
            mt5_tf = mt5.TIMEFRAME_M15 if tf == "15m" else mt5.TIMEFRAME_H1
            sfx = os.getenv("MT5_SYMBOL_SUFFIX", "")
            rates = mt5.copy_rates_from_pos(f"{symbol}{sfx}", mt5_tf, 0, 240)
            if rates is not None and len(rates) >= 205:
                df = pd.DataFrame(rates)
                df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
                return df
        try:
            p = "5d" if tf == "15m" else "1mo"
            df = yf.download(ticker, period=p, interval=tf, progress=False)
            if not df.empty and isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as err:
            log.error(f"Data fetch error on {symbol}: {err}")
            return pd.DataFrame()

    def evaluate_pair(self, symbol: str, meta: dict) -> dict | None:
        df_m15 = self._get_candles(symbol, meta["ticker"], "15m")
        df_h1 = self._get_candles(symbol, meta["ticker"], "1h")
        if len(df_m15) < 205 or len(df_h1) < 205:
            return None

        # H1 Macro Trend
        df_h1["EMA200"] = df_h1["Close"].ewm(span=200, adjust=False).mean()
        df_h1["EMA50"] = df_h1["Close"].ewm(span=50, adjust=False).mean()
        h1_c = float(df_h1["Close"].iloc[-1])
        h1_e200 = float(df_h1["EMA200"].iloc[-1])
        h1_e50 = float(df_h1["EMA50"].iloc[-1])

        # M15 Structure
        df_m15["EMA200"] = df_m15["Close"].ewm(span=200, adjust=False).mean()
        df_m15["EMA50"] = df_m15["Close"].ewm(span=50, adjust=False).mean()
        df_m15["EMA20"] = df_m15["Close"].ewm(span=20, adjust=False).mean()
        df_m15["RSI"] = self._calc_rsi(df_m15["Close"])
        df_m15["ADX"] = self._calc_adx(df_m15)
        df_m15["ATR"] = self._calc_atr(df_m15)

        curr = df_m15.iloc[-1]
        prev = df_m15.iloc[-2]
        price, open_p = float(curr["Close"]), float(curr["Open"])
        high_p, low_p = float(curr["High"]), float(curr["Low"])
        atr = float(curr["ATR"])
        adx_now, adx_prev = float(curr["ADX"]), float(prev["ADX"])
        rsi = float(curr["RSI"])
        e200, e50, e20 = float(curr["EMA200"]), float(curr["EMA50"]), float(curr["EMA20"])

        if np.isnan(atr) or atr <= 0 or (high_p - low_p) > (2.8 * atr):
            return None

        # Fetch Self-Learned Pair Parameters from Memory Engine
        pair_rules = memory_guard.get_pair_rules(symbol)
        pullback_limit = pair_rules["pullback_atr"]  # Evolves dynamically based on past losses

        direction = None
        if h1_c > h1_e200 and h1_e50 > h1_e200 and price > e200 and e20 > e50:
            if 50 <= rsi <= 65 and price > open_p and abs(low_p - e20) <= (pullback_limit * atr):
                direction = "BUY"
        elif h1_c < h1_e200 and h1_e50 < h1_e200 and price < e200 and e20 < e50:
            if 35 <= rsi <= 50 and price < open_p and abs(high_p - e20) <= (pullback_limit * atr):
                direction = "SELL"

        if not direction:
            return None

        # Check Loss Memory & Learned Thresholds
        allowed, reason, rec_meta = memory_guard.check_permission(symbol, direction, adx_now)
        if not allowed:
            log.info(f"Skipped {symbol} {direction}: {reason}")
            return None

        in_recovery = rec_meta.get("recovery_active", False)
        learned_min_adx = rec_meta.get("learned_min_adx", pair_rules["min_adx"])

        # Recovery mode boosts the ADX requirement higher for safety
        final_adx_threshold = learned_min_adx + 3.0 if in_recovery else learned_min_adx

        if adx_now < final_adx_threshold or adx_now < adx_prev:
            return None

        sl_mult = 1.2
        tp_mult = 2.0 if in_recovery else 1.6

        sl_dist = sl_mult * atr
        tp_dist = tp_mult * atr
        pip_sz = meta["pip_size"]
        dig = meta["digits"]

        sl_pips = round(sl_dist / pip_sz, 1)
        tp_pips = round(tp_dist / pip_sz, 1)
        if tp_pips < self.min_tp_pips:
            return None

        sl_val = round(price - sl_dist if direction == "BUY" else price + sl_dist, dig)
        tp_val = round(price + tp_dist if direction == "BUY" else price - tp_dist, dig)

        mode_label = f"ADX>={final_adx_threshold:.1f} (RECOVERY)" if in_recovery else f"ADX>={final_adx_threshold:.1f} (LEARNED)"

        return {
            "symbol": symbol,
            "action": direction,
            "entry_low": round(min(price, open_p), dig),
            "entry_high": round(max(price, open_p), dig),
            "current_price": round(price, dig),
            "sl": sl_val,
            "tp": tp_val,
            "tp1": tp_val,
            "tp2": round(price + (2.5 * atr) if direction == "BUY" else price - (2.5 * atr), dig),
            "tp3": round(price + (3.2 * atr) if direction == "BUY" else price - (3.2 * atr), dig),
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "rsi": round(rsi, 1),
            "adx": round(adx_now, 1),
            "setup": mode_label,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }

    async def scan_all(self, bypass_cooldown: bool = False, enforce_window: bool = True) -> pd.DataFrame:
        discovered = []
        now_ts = datetime.now(timezone.utc).timestamp()

        for sym, meta in self.market_map.items():
            if not bypass_cooldown and (now_ts - self.cooldowns.get(sym, 0)) < self.cooldown_sec:
                continue
            sig = self.evaluate_pair(sym, meta)
            if sig:
                if enforce_window and not self.is_within_trading_window():
                    log.info(f"Analyzed {sym} {sig['action']} setup outside trading hours (Standby).")
                    continue
                self.cooldowns[sym] = now_ts
                discovered.append(sig)

        return pd.DataFrame(discovered) if discovered else pd.DataFrame()

    async def close(self):
        if self.mt5_initialized and HAS_MT5:
            mt5.shutdown()

Scanner = LightweightScanner