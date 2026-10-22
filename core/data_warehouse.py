import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from core.logger import setup_system_logger

log = setup_system_logger("DataWarehouse")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class HistoricalDataWarehouse:
    def __init__(self):
        self.supabase: Client | None = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            except Exception as e:
                log.error(f"Warehouse Supabase connection error: {e}")

    def sync_historical_data(self, symbol: str, period="2y"):
        """Downloads multi-year historical data and caches it into Supabase."""
        if not self.supabase:
            return
        log.info(f"Syncing multi-year historical warehouse for {symbol}...")
        try:
            df = yf.download(symbol, period=period, interval="1h", progress=False)
            if df.empty:
                return

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            records = []
            for idx, row in df.iterrows():
                records.append({
                    "symbol": symbol,
                    "timestamp": idx.isoformat(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"])
                })

            # Batch upsert into Supabase historical table
            # (Chunks of 500 rows to respect request limits)
            for i in range(0, len(records), 500):
                chunk = records[i:i+500]
                self.supabase.table("historical_candles").upsert(chunk).execute()
                
            log.info(f"Successfully synced {len(records)} historical candles for {symbol}.")
        except Exception as e:
            log.error(f"Error syncing historical data for {symbol}: {e}")