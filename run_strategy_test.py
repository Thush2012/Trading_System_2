import asyncio

from core.data_fetcher import UnifiedDataFetcher
from core.strategy import StrategyEngine


async def main():
    fetcher = UnifiedDataFetcher()
    engine = StrategyEngine(fast_ema=9, slow_ema=21, rsi_period=14)

    # 1. Test Forex (EURUSD)
    print("--- Analyzing Forex: EURUSD (1h) ---")
    try:
        forex_raw = fetcher.fetch_forex_candles("EURUSD", timeframe="1h", count=50)
        forex_analyzed = engine.generate_signals(forex_raw)
        
        cols = ["timestamp", "close", "ema_fast", "ema_slow", "rsi", "signal"]
        print(forex_analyzed[cols].tail(5))
        
        latest_sig = forex_analyzed["signal"].iloc[-1]
        status = "BUY" if latest_sig == 1 else "SELL" if latest_sig == -1 else "NEUTRAL"
        print(f"Current EURUSD Signal: {status}")
    except Exception as e:
        print(f"Forex Error: {e}")

    # 2. Test Crypto (BTC/USDT)
    print("\n--- Analyzing Crypto: BTC/USDT (1h) ---")
    try:
        crypto_raw = await fetcher.fetch_crypto_candles("BTC/USDT", timeframe="1h", count=50)
        crypto_analyzed = engine.generate_signals(crypto_raw)
        
        cols = ["timestamp", "close", "ema_fast", "ema_slow", "rsi", "signal"]
        print(crypto_analyzed[cols].tail(5))

        latest_sig = crypto_analyzed["signal"].iloc[-1]
        status = "BUY" if latest_sig == 1 else "SELL" if latest_sig == -1 else "NEUTRAL"
        print(f"Current BTC/USDT Signal: {status}")
    except Exception as e:
        print(f"Crypto Error: {e}")

    await fetcher.close()

if __name__ == "__main__":
    asyncio.run(main())