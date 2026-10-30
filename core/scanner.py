import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone
import yfinance as yf

log = logging.getLogger("LightweightScanner")

class LightweightScanner:
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

    def is_within_trading_window(self) -> bool:
        """Forced to True to keep the execution engine active 24/7 without standby blocks."""
        return True

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        
        # RSI 14
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        
        # ATR 14
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14, min_periods=14).mean()
        
        # ADX 14 approximation
        up_move = df["high"] - df["high"].shift(1)
        down_move = df["low"] - df["low"]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr_smooth = tr.rolling(window=14, min_periods=14).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=14).mean() / tr_smooth.replace(0, np.nan))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=14).mean() / tr_smooth.replace(0, np.nan))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df["adx"] = dx.rolling(window=14).mean().fillna(20.0)
        
        # Z-Score (20 period)
        rolling_mean = df["close"].rolling(window=20).mean()
        rolling_std = df["close"].rolling(window=20).std()
        df["z_score"] = (df["close"] - rolling_mean) / rolling_std.replace(0, np.nan)
        df["z_score"] = df["z_score"].fillna(0.0)
        
        return df

    async def scan_all(self, bypass_cooldown: bool = True, enforce_window: bool = False) -> pd.DataFrame:
        """
        Scans monitored assets using yfinance, calculates indicators, and returns qualified setup rows.
        """
        log.info("Running lightweight multi-asset market scan...")
        scanned_data = []

        for symbol, info in self.market_map.items():
            ticker = info["ticker"]
            asset_type = info["asset_type"]
            try:
                df = yf.download(ticker, interval="15m", period="5d", progress=False)
                if df is None or df.empty or len(df) < 50:
                    continue
                
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
                df = self._calculate_indicators(df)
                
                curr = df.iloc[-1]
                
                current_price = float(curr["close"])
                atr = float(curr["atr"]) if not pd.isna(curr["atr"]) and curr["atr"] > 0 else current_price * 0.002
                rsi = float(curr["rsi"]) if not pd.isna(curr["rsi"]) else 50.0
                adx = float(curr["adx"]) if not pd.isna(curr["adx"]) else 20.0
                z_score = float(curr["z_score"]) if not pd.isna(curr["z_score"]) else 0.0
                
                # Evaluation logic for signals
                action = None
                if current_price > curr["ema200"] and curr["ema20"] > curr["ema50"] and 48 <= rsi <= 68 and abs(z_score) > 2.0 and adx >= 25.0:
                    action = "BUY"
                elif current_price < curr["ema200"] and curr["ema20"] < curr["ema50"] and 32 <= rsi <= 52 and abs(z_score) > 2.0 and adx >= 25.0:
                    action = "SELL"
                
                if action:
                    sl = round(current_price - (1.5 * atr) if action == "BUY" else current_price + (1.5 * atr), 5)
                    tp = round(current_price + (2.5 * atr) if action == "BUY" else current_price - (2.5 * atr), 5)
                    sl_pips = round(abs(current_price - sl) * (10000 if "JPY" not in symbol else 100), 1)
                    tp_pips = round(abs(tp - current_price) * (10000 if "JPY" not in symbol else 100), 1)
                    
                    # Define entry zone boundaries
                    entry_low = round(current_price - (0.15 * atr), 5)
                    entry_high = round(current_price + (0.15 * atr), 5)

                    scanned_data.append({
                        "symbol": symbol,
                        "action": action,
                        "current_price": current_price,
                        "entry_price": current_price,
                        "entry_low": entry_low,
                        "entry_high": entry_high,
                        "open": float(curr["open"]),
                        "high": float(curr["high"]),
                        "low": float(curr["low"]),
                        "sl": sl,
                        "tp": tp,
                        "sl_pips": sl_pips,
                        "tp_pips": tp_pips,
                        "rsi": round(rsi, 1),
                        "adx": round(adx, 1),
                        "z_score": round(z_score, 2),
                        "trend_1h": "BULLISH" if current_price > curr["ema50"] else "BEARISH",
                        "trend_4h": "BULLISH" if current_price > curr["ema200"] else "BEARISH",
                        "asset_type": asset_type,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
            except Exception as e:
                log.error(f"Error scanning {symbol}: {e}")

        return pd.DataFrame(scanned_data)

class MemoryGuardMock:
    def __init__(self):
        self.state = {"in_recovery": False, "deficit_usd": 0.0}

memory_guard = MemoryGuardMock()