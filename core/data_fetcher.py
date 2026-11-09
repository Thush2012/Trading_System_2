import ccxt.async_support as ccxt
import MetaTrader5 as mt5
import pandas as pd

# Map timeframe strings to MT5 constants
MT5_TIMEFRAME_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
}

class UnifiedDataFetcher:
    def __init__(self):
        self.crypto_client = ccxt.binance({"enableRateLimit": True})

    # --- Forex Fetcher (MetaTrader 5) ---
    def fetch_forex_candles(self, symbol: str, timeframe: str = "1h", count: int = 100) -> pd.DataFrame:
        """
        Fetches historical OHLCV data from MT5 and standardizes columns.
        """
        if not mt5.initialize():
            raise ConnectionError(f"MT5 initialization failed: {mt5.last_error()}")

        tf = MT5_TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            mt5.shutdown()
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Use: {list(MT5_TIMEFRAME_MAP.keys())}")

        if not mt5.symbol_select(symbol, True):
            mt5.shutdown()
            raise ValueError(f"Symbol '{symbol}' not found in MT5.")

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        mt5.shutdown()

        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No rates returned for {symbol}")

        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["volume"] = df["tick_volume"].astype(float)
        
        # Keep standardized columns only
        standard_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = df[standard_cols].copy()
        df["symbol"] = symbol
        df["asset_class"] = "FOREX"
        return df

    # --- Crypto Fetcher (CCXT) ---
    async def fetch_crypto_candles(self, symbol: str, timeframe: str = "1h", count: int = 100) -> pd.DataFrame:
        """
        Fetches historical OHLCV data via CCXT and standardizes columns.
        """
        try:
            ohlcv = await self.crypto_client.fetch_ohlcv(symbol, timeframe=timeframe, limit=count)
            if not ohlcv:
                raise RuntimeError(f"No data returned for {symbol}")

            # CCXT returns: [timestamp_ms, open, high, low, close, volume]
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df["symbol"] = symbol
            df["asset_class"] = "CRYPTO"
            return df
        except Exception as e:
            raise RuntimeError(f"Crypto fetch failed for {symbol}: {e}")

    async def close(self):
        """Closes async sessions."""
        await self.crypto_client.close()