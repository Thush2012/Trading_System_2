import asyncio

from core.backtester import BacktestEngine
from core.data_fetcher import UnifiedDataFetcher
from core.strategy import StrategyEngine


async def run_simulation():
    fetcher = UnifiedDataFetcher()
    strategy = StrategyEngine(fast_ema=9, slow_ema=21, rsi_period=14)
    backtester = BacktestEngine(initial_capital=10000.0)

    # 1. Backtest Forex: EURUSD (Last 1000 1-hour candles)
    print("==================================================")
    print("         RUNNING FOREX BACKTEST: EURUSD (1H)      ")
    print("==================================================")
    try:
        raw_forex = fetcher.fetch_forex_candles("EURUSD", timeframe="1h", count=1000)
        analyzed_forex = strategy.generate_signals(raw_forex)
        forex_results = backtester.run(analyzed_forex)

        print(f"Candles Tested  : {len(analyzed_forex)}")
        print(f"Starting Capital: ${forex_results['initial_capital']:,.2f}")
        print(f"Ending Balance  : ${forex_results['final_balance']:,.2f}")
        print(f"Net Return      : {forex_results['total_return_pct']}%")
        print(f"Total Trades    : {forex_results['total_trades']}")
        print(f"Win Rate        : {forex_results['win_rate_pct']}%")
        print(f"Profit Factor   : {forex_results['profit_factor']}")
        print(f"Max Drawdown    : {forex_results['max_drawdown_pct']}%")
    except Exception as e:
        print(f"Forex Backtest Error: {e}")

    # 2. Backtest Crypto: BTC/USDT (Last 1000 1-hour candles)
    print("\n==================================================")
    print("         RUNNING CRYPTO BACKTEST: BTC/USDT (1H)   ")
    print("==================================================")
    try:
        raw_crypto = await fetcher.fetch_crypto_candles("BTC/USDT", timeframe="1h", count=1000)
        analyzed_crypto = strategy.generate_signals(raw_crypto)
        crypto_results = backtester.run(analyzed_crypto)

        print(f"Candles Tested  : {len(analyzed_crypto)}")
        print(f"Starting Capital: ${crypto_results['initial_capital']:,.2f}")
        print(f"Ending Balance  : ${crypto_results['final_balance']:,.2f}")
        print(f"Net Return      : {crypto_results['total_return_pct']}%")
        print(f"Total Trades    : {crypto_results['total_trades']}")
        print(f"Win Rate        : {crypto_results['win_rate_pct']}%")
        print(f"Profit Factor   : {crypto_results['profit_factor']}")
        print(f"Max Drawdown    : {crypto_results['max_drawdown_pct']}%")
    except Exception as e:
        print(f"Crypto Backtest Error: {e}")

    await fetcher.close()

if __name__ == "__main__":
    asyncio.run(run_simulation())