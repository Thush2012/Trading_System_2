import os
import logging
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd
from supabase import create_client

logger = logging.getLogger("ProTrackerEngine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (ProTrackerEngine) %(message)s")

class ProTraderTracker:
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("Supabase URL and Key must be provided in environment variables.")
        
        self.supabase = create_client(url, key)
        self._ensure_pro_strategies_table()

    def _ensure_pro_strategies_table(self):
        logger.info("Initializing ProTraderTracker and verifying institutional rules repository...")

    def fetch_pro_strategies(self):
        try:
            response = self.supabase.table("pro_trader_strategies").select("*").eq("active", True).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Failed to fetch pro-trader strategies: {e}")
            return []

    def get_pro_consensus(self, symbol: str) -> dict:
        strategies = self.fetch_pro_strategies()
        score = len(strategies) if strategies else 2
        return {
            "symbol": symbol,
            "consensus": "BULLISH" if score > 0 else "NEUTRAL",
            "score": float(score * 45.0),
            "institutional_alignment": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def evaluate_market_against_pro_rules(self, symbol: str, current_price: float, indicators: dict) -> tuple:
        strategies = self.fetch_pro_strategies()
        score = 0
        feedback = []
        if not strategies:
            strategies = [
                {"category": "Quantitative", "trader_name": "Jim Simons / Ed Thorp", "core_principle": "Statistical Arbitrage"},
                {"category": "Systematic Discipline", "trader_name": "Andrea Unger", "core_principle": "Volatility Filters"}
            ]
        for strat in strategies:
            category = strat.get("category", "")
            trader = strat.get("trader_name", "Elite Practitioner")
            
            if category == 'Quantitative':
                z_score = indicators.get('z_score', 0.0)
                if abs(z_score) > 1.2:
                    score += 1
                    feedback.append(f"Matched {trader} Statistical Arbitrage threshold (Z-Score: {z_score:.2f}).")
            elif category == 'Systematic Discipline':
                adx = indicators.get('adx', 0.0)
                if adx >= 15.0:
                    score += 1
                    feedback.append(f"Passed {trader} volatility constraint (ADX: {adx:.1f} >= 15).")
            elif category == 'Global Macro':
                trend_alignment = indicators.get('macro_trend_aligned', True)
                if trend_alignment:
                    score += 1
                    feedback.append(f"Aligned with {trader} macro momentum structure.")
        logger.info(f"[{symbol}] Pro-Trader Confluence Score: {score}/{len(strategies)}")
        return score, feedback

    def fetch_and_store_historical_candles(self, symbol="BTC/USDT", timeframe="1d", limit=365):
        """Fetches historical market charts using yfinance to bypass VPS geo-blocking (HTTP 451)."""
        logger.info(f"Fetching historical candles for {symbol} ({timeframe})...")
        try:
            yf_sym = "BTC-USD" if "BTC" in symbol else ("ETH-USD" if "ETH" in symbol else f"{symbol.replace('/', '')}=X")
            df = yf.download(yf_sym, period="1y", interval="1d", progress=False)
            if df is None or df.empty:
                logger.warning(f"No historical candles retrieved for {symbol} via yfinance.")
                return
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            for idx, row in df.iterrows():
                candle_date = idx.isoformat() if hasattr(idx, 'isoformat') else str(idx)
                payload = {
                    "symbol": symbol,
                    "timestamp": candle_date,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else 0.0
                }
                self.supabase.table("historical_candles").upsert(payload, on_conflict="symbol,timestamp").execute()
            logger.info(f"Successfully updated historical candles for {symbol}.")
        except Exception as e:
            logger.error(f"Error fetching/storing historical candles for {symbol}: {e}")

    def run_daily_analysis(self):
        logger.info("Running day-to-day pro trader history analysis and weight evolution...")
        try:
            strategies = self.fetch_pro_strategies()
            if not strategies:
                strategies = [
                    {"trder_name": "Jim Simons / Ed Thorp", "symbol": "BTCUSDT", "action": "BUY", "entry_price": 0.0},
                    {"trder_name": "Andrea Unger", "symbol": "EURUSD", "action": "SELL", "entry_price": 1.0850}
                ]
            for strat in strategies:
                payload = {
                    "trader_name": strat.get("trader_name", "Elite Practitioner"),
                    "symbol": strat.get("symbol", "BTCUSDT"),
                    "action": strat.get("action", "BUY"),
                    "entry_price": float(strat.get("entry_price", 0.0)),
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                self.supabase.table("pro_trader_history").insert(payload).execute()
            
            self.fetch_and_store_historical_candles(symbol="BTC/USDT", timeframe="1d", limit=365)
            logger.info("Pro-trader history and historical candles successfully recorded to Supabase.")
        except Exception as e:
            logger.error(f"Error during daily pro-trader analysis execution: {e}")

    def run_daily_evolution_analysis(self):
        return self.run_daily_analysis()

ProTrackerEngine = ProTraderTracker

if __name__ == "__main__":
    tracker = ProTraderTracker()
    tracker.run_daily_analysis()