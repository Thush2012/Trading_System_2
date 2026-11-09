import asyncio

from core.data_fetcher import UnifiedDataFetcher


async def main():
    fetcher = UnifiedDataFetcher()

    print("Fetching Forex data (EURUSD, 1h)...")
    try:
        forex_df = fetcher.fetch_forex_candles("EURUSD", timeframe="1h", count=5)
        print(forex_df)
    except Exception as e:
        print(f"Forex Error: {e}")

    print("\nFetching Crypto data (BTC/USDT, 1h)...")
    try:
        crypto_df = await fetcher.fetch_crypto_candles("BTC/USDT", timeframe="1h", count=5)
        print(crypto_df)
    except Exception as e:
        print(f"Crypto Error: {e}")

    await fetcher.close()

if __name__ == "__main__":
    asyncio.run(main())