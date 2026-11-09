import os

from dotenv import load_dotenv

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", 0.01))
    MAX_DAILY_DRAWDOWN_PCT = float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", 0.03))

    FAST_EMA = int(os.getenv("FAST_EMA", 9))
    SLOW_EMA = int(os.getenv("SLOW_EMA", 21))
    RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
    DEFAULT_TIMEFRAME = os.getenv("DEFAULT_TIMEFRAME", "1h")

    FOREX_WATCHLIST = [s.strip() for s in os.getenv("FOREX_WATCHLIST", "EURUSD,GBPUSD").split(",") if s.strip()]
    CRYPTO_WATCHLIST = [s.strip() for s in os.getenv("CRYPTO_WATCHLIST", "BTC/USDT,ETH/USDT").split(",") if s.strip()]

    BREAKEVEN_PIPS = float(os.getenv("BREAKEVEN_PIPS", 15.0))
    TRAIL_DISTANCE_PIPS = float(os.getenv("TRAIL_DISTANCE_PIPS", 10.0))

    # Spread Protection
    MAX_FOREX_SPREAD_POINTS = int(os.getenv("MAX_FOREX_SPREAD_POINTS", 25))
    MAX_CRYPTO_SPREAD_BPS = float(os.getenv("MAX_CRYPTO_SPREAD_BPS", 15.0))