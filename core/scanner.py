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

log = setup_system_logger("MultiTFScanner")
memory_guard = LossMemoryEngine()

FOREX_MARKETS = {
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread": 1.8},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5, "max_spread": 2.0},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread": 1.8},
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread": 1.8},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread": 2.6},
}

# Multi-Timeframe Definitions & Scaling Rules
TIMEFRAME_CONFIG = {
    "5m": {
        "macro_tf": "15m",
        "min_pips": 8.0,
        "sl_mult": 1.3,
        "tp_mult": 1.5,
        "desc": "SCALP"
    },
    "15m": {
        "macro_tf": "1h",
        "min_pips": 15.0,
        "sl_mult": 1.2,
        "tp_mult": 1.6,
        "desc": "INTRADAY"
    },
    "1h": {
        "macro_tf": "1d",
        "min_pips": 25.0,
        "sl_mult": 1.5,
        "tp_mult": 2.2,
        "desc": "MACRO"
    }
}

class LightweightScanner:
    def __init__(self):
        self.market_map = FOREX_MARKETS
        self.cooldowns = {}
        self.cooldown_sec = 900  # 15-min cooldown per symbol/timeframe combo
        self.slt_tz = pytz.timezone("Asia/Colombo")
        self.mt5_initialized = False
        self._connect_mt5()

    def _connect_mt5(self):
        if datetime.now(self.slt_tz).weekday() >= 5:
            return
        if HAS_MT5 and mt5.initialize():
            self.mt5_initialized = True
            log.info("MT5 Live Feed active for Multi-TF scanner.")

    def is_within_trading_window(self) -> bool:
        """Active Mon-Fri from 8:00 AM to 9:30 PM SLT, excluding 6:30 - 8:30 PM power cut."""
        now_slt = datetime.now(self.slt_tz)
        if now_slt.weekday() >= 5:
            return False
        dec_hour = now_slt.hour + (now_slt.minute / 60.0)
        
        is_in_span = 8.0 <= dec_hour <= 21.5
        is_power_cut = 18.5 <= dec_hour <= 20.5
        
        return is_in_span and not is_power_cut

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
            tf_map = {
                "5m": mt5.TIMEFRAME_M5,
                "15m": mt5.TIMEFRAME_M15,
                "1h": mt5.TIMEFRAME_H1,
                "1d": mt5.TIMEFRAME_D1
            }
            mt5_tf = tf_map.get(tf, mt5.TIMEFRAME_M15)
            sfx = os.getenv("MT5_SYMBOL_SUFFIX", "")
            rates = mt5.copy_rates_from_pos(f"{symbol}{sfx}", mt5_tf, 0, 240)
            if rates is not None and len(rates) >= 150:
                df = pd.DataFrame(rates)
                df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
                return df
        try:
            p_map = {"5m": "3d", "15m": "5d", "1h": "1mo", "1d": "1y"}
            df = yf.download(ticker, period=p_map.get(tf, "1mo"), interval=tf, progress=False)
            if not df.empty and isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as err:
            log.error(f"Data fetch error on {symbol} ({tf}): {err}")
            return pd.DataFrame()

    def evaluate_timeframe(self, symbol: str, meta: dict, tf: str) -> dict | None:
        cfg = TIMEFRAME_CONFIG[tf]
        macro_tf = cfg["macro_tf"]

        df_base = self._get_candles(symbol, meta["ticker"], tf)
        df_macro = self._get_candles(symbol, meta["ticker"], macro_tf)
        if len(df_base) < 140 or len(df_macro) < 100:
            return None

        # Macro Trend Context
        df_macro["EMA200"] = df_macro["Close"].ewm(span=min(200, len(df_macro)-5), adjust=False).mean()
        macro_c = float(df_macro["Close"].iloc[-1])
        macro_e200 = float(df_macro["EMA200"].iloc[-1])

        # Base Timeframe Structure
        df_base["EMA200"] = df_base["Close"].ewm(span=min(200, len(df_base)-5), adjust=False).mean()
        df_base["EMA50"] = df_base["Close"].ewm(span=50, adjust=False).mean()
        df_base["EMA20"] = df_base["Close"].ewm(span=20, adjust=False).mean()
        df_base["RSI"] = self._calc_rsi(df_base["Close"])
        df_base["ADX"] = self._calc_adx(df_base)
        df_base["ATR"] = self._calc_atr(df_base)

        curr = df_base.iloc[-1]
        prev = df_base.iloc[-2]
        price, open_p = float(curr["Close"]), float(curr["Open"])
        high_p, low_p = float(curr["High"]), float(curr["Low"])
        atr = float(curr["ATR"])
        adx_now = float(curr["ADX"])
        rsi = float(curr["RSI"])
        e200, e50, e20 = float(curr["EMA200"]), float(curr["EMA50"]), float(curr["EMA20"])

        if np.isnan(atr) or atr <= 0 or (high_p - low_p) > (3.0 * atr):
            return None

        pair_rules = memory_guard.get_pair_rules(symbol)
        pullback_limit = pair_rules["pullback_atr"]

        direction = None
        if macro_c > macro_e200 and price > e200 and e20 > e50:
            if 48 <= rsi <= 68 and price > open_p and abs(low_p - e20) <= (pullback_limit * atr):
                direction = "BUY"
        elif macro_c < macro_e200 and price < e200 and e20 < e50:
            if 32 <= rsi <= 52 and price < open_p and abs(high_p - e20) <= (pullback_limit * atr):
                direction = "SELL"

        if not direction:
            return None

        # Memory & Recovery Gate Check
        allowed, reason, rec_meta = memory_guard.check_permission(symbol, direction, adx_now)
        if not allowed:
            return None

        in_recovery = rec_meta.get("recovery_active", False)
        learned_min_adx = rec_meta.get("learned_min_adx", pair_rules["min_adx"])
        final_adx_threshold = (learned_min_adx + 2.0) if in_recovery else learned_min_adx

        if adx_now < final_adx_threshold:
            return None

        sl_dist = cfg["sl_mult"] * atr
        tp_dist = (cfg["tp_mult"] + 0.4 if in_recovery else cfg["tp_mult"]) * atr
        pip_sz = meta["pip_size"]
        dig = meta["digits"]

        sl_pips = round(sl_dist / pip_sz, 1)
        tp_pips = round(tp_dist / pip_sz, 1)
        if tp_pips < cfg["min_pips"]:
            return None

        sl_val = round(price - sl_dist if direction == "BUY" else price + sl_dist, dig)
        tp_val = round(price + tp_dist if direction == "BUY" else price - tp_dist, dig)
        mode_label = f"{tf.upper()} {cfg['desc']} (RECOVERY)" if in_recovery else f"{tf.upper()} {cfg['desc']}"

        return {
            "symbol": symbol,
            "timeframe": tf,
            "action": direction,
            "entry_low": round(min(price, open_p), dig),
            "entry_high": round(max(price, open_p), dig),
            "current_price": round(price, dig),
            "sl": sl_val,
            "tp": tp_val,
            "tp1": tp_val,
            "tp2": round(price + (2.2 * atr) if direction == "BUY" else price - (2.2 * atr), dig),
            "tp3": round(price + (3.0 * atr) if direction == "BUY" else price - (3.0 * atr), dig),
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

        # Scan all 5 pairs across all 3 timeframes (5m, 15m, 1h)
        for sym, meta in self.market_map.items():
            for tf in ["5m", "15m", "1h"]:
                cooldown_key = f"{sym}_{tf}"
                if not bypass_cooldown and (now_ts - self.cooldowns.get(cooldown_key, 0)) < self.cooldown_sec:
                    continue
                
                sig = self.evaluate_timeframe(sym, meta, tf)
                if sig:
                    if enforce_window and not self.is_within_trading_window():
                        continue
                    self.cooldowns[cooldown_key] = now_ts
                    discovered.append(sig)

        return pd.DataFrame(discovered) if discovered else pd.DataFrame()

    async def close(self):
        if self.mt5_initialized and HAS_MT5:
            mt5.shutdown()

Scanner = LightweightScanner