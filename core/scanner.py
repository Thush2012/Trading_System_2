import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone
import yfinance as yf

log = logging.getLogger("InstitutionalScanner")

class InstitutionalScanner:
    def __init__(self):
        self.market_map = {
            "USDJPY": {"ticker": "USDJPY=X", "asset_type": "FOREX"},
            "EURGBP": {"ticker": "EURGBP=X", "asset_type": "FOREX"},
            "AUDUSD": {"ticker": "AUDUSD=X", "asset_type": "FOREX"},
            "EURUSD": {"ticker": "EURUSD=X", "asset_type": "FOREX"},
            "GBPJPY": {"ticker": "GBPJPY=X", "asset_type": "FOREX"},
            "BTCUSDT": {"ticker": "BTC-USD", "asset_type": "CRYPTO"},
            "ETHUSDT": {"ticker": "ETH-USD", "asset_type": "CRYPTO"}
        }
        # Tracks active signal state to instantly catch reversals while preventing duplicate spam
        self.last_signal_states = {}

    def is_within_trading_window(self) -> bool:
        return True

    def _detect_market_regime(self, df: pd.DataFrame) -> str:
        """Pillar 1: Hidden Regime Classifier (Trend vs Chop via Volatility & ADX)"""
        recent_adx = df["adx"].iloc[-1]
        atr_pct = (df["atr"].iloc[-1] / df["close"].iloc[-1]) * 100
        
        if recent_adx >= 25.0 and atr_pct > 0.15:
            return "HIGH_VOLATILITY_TREND"
        elif recent_adx < 20.0:
            return "SIDEWAYS_CHOP"
        return "STANDARD_REGIME"

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        
        # RSI 14
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        rs = gain.rolling(14).mean() / loss.rolling(14).mean().replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        
        # ATR 14
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()
        
        # ADX 14
        up_move = df["high"] - df["high"].shift(1)
        down_move = df["low"].shift(1) - df["low"]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr_smooth = tr.rolling(14).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(14).mean() / tr_smooth.replace(0, np.nan))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(14).mean() / tr_smooth.replace(0, np.nan))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df["adx"] = dx.rolling(14).mean().fillna(20.0)
        
        # Z-Score
        rolling_mean = df["close"].rolling(20).mean()
        rolling_std = df["close"].rolling(20).std()
        df["z_score"] = ((df["close"] - rolling_mean) / rolling_std.replace(0, np.nan)).fillna(0.0)
        return df

    async def scan_all(self, bypass_cooldown: bool = True, enforce_window: bool = False) -> pd.DataFrame:
        log.info("Running Institutional Multi-Tier Market Scan with Regime & Confluence Filters...")
        scanned_data = []

        for symbol, info in self.market_map.items():
            try:
                df = yf.download(info["ticker"], interval="15m", period="5d", progress=False)
                if df is None or df.empty or len(df) < 50:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
                df = self._calculate_indicators(df)
                
                curr = df.iloc[-1]
                current_price = float(curr["close"])
                regime = self._detect_market_regime(df)
                
                # Pillar 4: Suppress signals during choppy low-volatility regimes
                if regime == "SIDEWAYS_CHOP":
                    continue

                # Pillar 2: Multi-Timeframe Structural Confluence (4H & Daily approximation)
                trend_4h = "BULLISH" if current_price > curr["ema50"] else "BEARISH"
                trend_daily = "BULLISH" if current_price > curr["ema200"] else "BEARISH"

                action = None
                rsi = float(curr["rsi"])
                z_score = float(curr["z_score"])
                adx = float(curr["adx"])

                if trend_4h == "BULLISH" and trend_daily == "BULLISH" and current_price > curr["ema200"] and 50 <= rsi <= 68 and z_score > 1.5 and adx >= 25.0:
                    action = "BUY"
                elif trend_4h == "BEARISH" and trend_daily == "BEARISH" and current_price < curr["ema200"] and 32 <= rsi <= 50 and z_score < -1.5 and adx >= 25.0:
                    action = "SELL"

                # Direction-Flip Anti-Spam Control
                previous_action = self.last_signal_states.get(symbol)
                if action:
                    if previous_action == action:
                        continue
                    self.last_signal_states[symbol] = action

                    atr = float(curr["atr"]) if not pd.isna(curr["atr"]) and curr["atr"] > 0 else current_price * 0.002
                    sl = round(current_price - (1.5 * atr) if action == "BUY" else current_price + (1.5 * atr), 5)
                    tp = round(current_price + (2.5 * atr) if action == "BUY" else current_price - (2.5 * atr), 5)

                    scanned_data.append({
                        "symbol": symbol,
                        "action": action,
                        "current_price": current_price,
                        "entry_price": current_price,
                        "entry_low": round(current_price - (0.15 * atr), 5),
                        "entry_high": round(current_price + (0.15 * atr), 5),
                        "open": float(curr["open"]),
                        "high": float(curr["high"]),
                        "low": float(curr["low"]),
                        "sl": sl,
                        "tp": tp,
                        "sl_pips": round(abs(current_price - sl) * (10000 if "JPY" not in symbol else 100), 1),
                        "tp_pips": round(abs(tp - current_price) * (10000 if "JPY" not in symbol else 100), 1),
                        "rsi": round(rsi, 1),
                        "adx": round(adx, 1),
                        "z_score": round(z_score, 2),
                        "trend_1h": trend_4h,
                        "trend_4h": trend_daily,
                        "asset_type": info["asset_type"],
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
            except Exception as e:
                log.error(f"Error scanning {symbol}: {e}")

        return pd.DataFrame(scanned_data)

class MemoryGuardMock:
    def __init__(self):
        self.state = {"in_recovery": False, "deficit_usd": 0.0}

memory_guard = MemoryGuardMock()