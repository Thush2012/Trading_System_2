import os
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import pytz
from core.logger import setup_system_logger
from core.loss_memory import LossMemoryEngine
from core.institutional_filter import InstitutionalFilterEngine

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

log = setup_system_logger("InstitutionalScanner")
memory_guard = LossMemoryEngine()
inst_filter = InstitutionalFilterEngine()

MARKET_CONFIG = {
    "USDJPY": {"ticker": "USDJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread": 2.0, "asset_type": "FOREX"},
    "EURGBP": {"ticker": "EURGBP=X", "pip_size": 0.0001, "digits": 5, "max_spread": 2.2, "asset_type": "FOREX"},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread": 2.0, "asset_type": "FOREX"},
    "EURUSD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "digits": 5, "max_spread": 2.0, "asset_type": "FOREX"},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip_size": 0.01,   "digits": 3, "max_spread": 3.0, "asset_type": "FOREX"},
    "BTCUSDT": {"ticker": "BTC-USD", "pip_size": 1.0,   "digits": 2, "max_spread": 20.0, "asset_type": "CRYPTO"},
    "ETHUSDT": {"ticker": "ETH-USD", "pip_size": 0.1,    "digits": 2, "max_spread": 10.0, "asset_type": "CRYPTO"},
}

TIMEFRAME_CONFIG = {
    "5m": {"macro_tf": "15m", "min_adx": 21.0, "min_pips": 7.0, "sl_mult": 1.2, "tp_mult": 1.3, "desc": "FAST SCALP"},
    "15m": {"macro_tf": "1h", "min_adx": 23.0, "min_pips": 12.0, "sl_mult": 1.3, "tp_mult": 1.6, "desc": "INTRADAY"},
    "1h": {"macro_tf": "1d", "min_adx": 24.0, "min_pips": 20.0, "sl_mult": 1.5, "tp_mult": 2.0, "desc": "SWING"}
}

class LightweightScanner:
    def __init__(self):
        self.market_map = MARKET_CONFIG
        self.cooldowns = {}
        self.cooldown_sec = 600
        self.slt_tz = pytz.timezone("Asia/Colombo")
        self.mt5_initialized = False
        self._connect_mt5()

    def _connect_mt5(self):
        if datetime.now(self.slt_tz).weekday() >= 5:
            return
        if HAS_MT5 and mt5.initialize():
            self.mt5_initialized = True

    def is_within_trading_window(self) -> bool:
        now_slt = datetime.now(self.slt_tz)
        if now_slt.weekday() >= 5:
            return False
        dec_hour = now_slt.hour + (now_slt.minute / 60.0)
        return (8.0 <= dec_hour <= 21.5) and not (18.5 <= dec_hour <= 20.5)

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

    def _get_candles(self, symbol: str, meta: dict, tf: str) -> pd.DataFrame:
        asset_type, ticker = meta["asset_type"], meta["ticker"]
        if asset_type == "FOREX" and self.mt5_initialized and datetime.now(self.slt_tz).weekday() < 5:
            tf_map = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "1h": mt5.TIMEFRAME_H1, "1d": mt5.TIMEFRAME_D1}
            rates = mt5.copy_rates_from_pos(f"{symbol}{os.getenv('MT5_SYMBOL_SUFFIX', '')}", tf_map.get(tf, mt5.TIMEFRAME_M15), 0, 200)
            if rates is not None and len(rates) >= 100:
                df = pd.DataFrame(rates)
                df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
                return df
        try:
            p_map = {"5m": "2d", "15m": "5d", "1h": "1mo", "1d": "1y"}
            df = yf.download(ticker, period=p_map.get(tf, "1mo"), interval=tf, progress=False)
            if not df.empty and isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception:
            return pd.DataFrame()

    def evaluate_timeframe(self, symbol: str, meta: dict, tf: str) -> dict | None:
        cfg = TIMEFRAME_CONFIG[tf]
        df_base = self._get_candles(symbol, meta, tf)
        df_macro = self._get_candles(symbol, meta, cfg["macro_tf"])
        if len(df_base) < 80 or len(df_macro) < 60:
            return None

        # Macro Trend Context
        df_macro["EMA200"] = df_macro["Close"].ewm(span=200, adjust=False).mean()
        macro_c, macro_e200 = float(df_macro["Close"].iloc[-1]), float(df_macro["EMA200"].iloc[-1])

        # Base Structure & Order Block Identification
        df_base["EMA100"] = df_base["Close"].ewm(span=100, adjust=False).mean()
        df_base["EMA50"] = df_base["Close"].ewm(span=50, adjust=False).mean()
        df_base["EMA20"] = df_base["Close"].ewm(span=20, adjust=False).mean()
        df_base["RSI"] = self._calc_rsi(df_base["Close"])
        df_base["ADX"] = self._calc_adx(df_base)
        df_base["ATR"] = self._calc_atr(df_base)

        curr = df_base.iloc[-1]
        price, open_p, high_p, low_p = float(curr["Close"]), float(curr["Open"]), float(curr["High"]), float(curr["Low"])
        atr, adx_now, rsi = float(curr["ATR"]), float(curr["ADX"]), float(curr["RSI"])
        e100, e50, e20 = float(curr["EMA100"]), float(curr["EMA50"]), float(curr["EMA20"])

        if np.isnan(atr) or atr <= 0 or (high_p - low_p) > (3.5 * atr):
            return None

        pair_rules = memory_guard.get_pair_rules(symbol)
        pullback_limit = max(pair_rules["pullback_atr"], 0.65)

        direction = None
        if macro_c > macro_e200 and price > e100 and e20 > e50:
            if 45 <= rsi <= 70 and price > open_p and abs(low_p - e20) <= (pullback_limit * atr):
                direction = "BUY"
        elif macro_c < macro_e200 and price < e100 and e20 < e50:
            if 30 <= rsi <= 55 and price < open_p and abs(high_p - e20) <= (pullback_limit * atr):
                direction = "SELL"

        if not direction:
            return None

        # 1. Self-Learning Memory Gate Check
        allowed, reason, rec_meta = memory_guard.check_permission(symbol, direction, adx_now)
        if not allowed:
            return None

        # 2. Institutional & Intermarket Filter Check
        inst_ok, inst_reason, inst_meta = inst_filter.evaluate_institutional_confluence(symbol, direction, df_base)
        if not inst_ok:
            return None

        in_recovery = rec_meta.get("recovery_active", False)
        base_adx_req = max(cfg["min_adx"], pair_rules["min_adx"] - 2.0)
        final_adx_threshold = (base_adx_req + 2.0) if in_recovery else base_adx_req

        if adx_now < final_adx_threshold:
            return None

        # Dynamic Volatility Regime Multiplier (Widen targets if explosive breakout regime)
        vol_regime = inst_meta.get("volatility_regime", "NORMAL")
        tp_multiplier = 2.4 if vol_regime == "EXPLOSIVE_BREAKOUT" else cfg["tp_mult"]

        sl_dist = cfg["sl_mult"] * atr
        tp_dist = tp_multiplier * atr
        pip_sz, dig = meta["pip_size"], meta["digits"]

        sl_pips = round(sl_dist / pip_sz, 1)
        tp_pips = round(tp_dist / pip_sz, 1)
        if tp_pips < cfg["min_pips"]:
            return None

        sl_val = round(price - sl_dist if direction == "BUY" else price + sl_dist, dig)
        tp_val = round(price + tp_dist if direction == "BUY" else price - tp_dist, dig)
        mode_label = f"{tf.upper()} INST_PRO ({vol_regime})"

        return {
            "symbol": symbol,
            "timeframe": tf,
            "asset_type": meta["asset_type"],
            "action": direction,
            "entry_low": round(min(price, open_p), dig),
            "entry_high": round(max(price, open_p), dig),
            "current_price": round(price, dig),
            "sl": sl_val,
            "tp": tp_val,
            "tp1": tp_val,
            "tp2": round(price + (2.0 * atr) if direction == "BUY" else price - (2.0 * atr), dig),
            "tp3": round(price + (2.8 * atr) if direction == "BUY" else price - (2.8 * atr), dig),
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