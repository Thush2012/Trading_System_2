import asyncio

import ccxt.async_support as ccxt
import MetaTrader5 as mt5


def test_forex():
    print("--- 1. Testing Forex (MetaTrader 5) ---")
    
    # Initialize connection to the MT5 terminal installed on your PC
    if not mt5.initialize():
        print(f"Failed to connect to MT5. Error: {mt5.last_error()}")
        print("Tip: Make sure the MetaTrader 5 desktop application is open and logged into an account.")
        return False

    symbol = "EURUSD"
    # Ensure EURUSD is visible in Market Watch
    if not mt5.symbol_select(symbol, True):
        print(f"Symbol '{symbol}' not found or could not be selected.")
        mt5.shutdown()
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick:
        print(f"Forex OK: {symbol} | Bid: {tick.bid} | Ask: {tick.ask}")
    else:
        print("Forex Failed: Could not pull live tick.")
        
    mt5.shutdown()
    return True

async def test_crypto():
    print("\n--- 2. Testing Crypto (CCXT / Binance Public Feed) ---")
    
    # Binance public ticker does not require an API key to read prices
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        ticker = await exchange.fetch_ticker("BTC/USDT")
        print(f"Crypto OK: BTC/USDT | Last Price: ${ticker['last']:,.2f}")
    except Exception as e:
        print(f"Crypto Failed: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    test_forex()
    asyncio.run(test_crypto())