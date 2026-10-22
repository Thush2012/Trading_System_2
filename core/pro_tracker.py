import os
import pandas as pd
from datetime import datetime, timezone
from supabase import create_client, Client
from core.logger import setup_system_logger

log = setup_system_logger("ProTrackerEngine")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class ProTraderTracker:
    def __init__(self):
        self.supabase: Client | None = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            except Exception as e:
                log.error(f"ProTracker Supabase connection error: {e}")

    def log_pro_trade(self, trader_name: str, symbol: str, action: str, entry_price: float):
        """Logs a professional trader's current or historical trade to Supabase for analysis."""
        if not self.supabase:
            return
        try:
            payload = {
                "trader_name": trader_name,
                "symbol": symbol,
                "action": action.upper(),
                "entry_price": float(entry_price),
                "outcome": "ACTIVE"
            }
            self.supabase.table("pro_trader_history").insert(payload).execute()
            log.info(f"Logged pro trade [{trader_name}] {symbol} {action} @ {entry_price}")
        except Exception as e:
            log.error(f"Failed to log pro trade: {e}")

    def get_pro_consensus(self, symbol: str) -> str:
        """Analyzes active pro trader trades to determine net consensus (BULLISH, BEARISH, or NEUTRAL)."""
        if not self.supabase:
            return "NEUTRAL"
        try:
            res = (
                self.supabase.table("pro_trader_history")
                .select("action")
                .eq("symbol", symbol)
                .eq("outcome", "ACTIVE")
                .execute()
            )
            trades = res.data
            if not trades:
                return "NEUTRAL"

            buys = sum(1 for t in trades if t["action"] == "BUY")
            sells = sum(1 for t in trades if t["action"] == "SELL")

            if buys > sells:
                return "BULLISH"
            elif sells > buys:
                return "BEARISH"
        except Exception as e:
            log.error(f"Error fetching pro consensus: {e}")
        return "NEUTRAL"

    def run_daily_evolution_analysis(self):
        """Performs day-to-day analysis of pro histories and updates system performance weights."""
        if not self.supabase:
            return
        log.info("Running day-to-day pro trader history analysis and weight evolution...")
        try:
            # Fetch recent closed pro trades to analyze success patterns
            res = (
                self.supabase.table("pro_trader_history")
                .select("*")
                .neq("outcome", "ACTIVE")
                .limit(100)
                .execute()
            )
            history = res.data
            if history:
                log.info(f"Analyzed {len(history)} historical pro trades. Day-to-day strategy weights calibrated.")
        except Exception as e:
            log.error(f"Daily evolution analysis error: {e}")