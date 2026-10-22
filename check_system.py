import os
from dotenv import load_dotenv
from supabase import create_client
import MetaTrader5 as mt5
import ccxt

load_dotenv()

print("--- SYSTEM DIAGNOSTIC CHECK ---")

# 1. Check Supabase Connection & Tables
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
if url and key:
    try:
        supabase = create_client(url, key)
        res = supabase.table("trade_signals").select("id").limit(1).execute()
        print("[OK] Supabase connected and table 'trade_signals' is accessible.")
    except Exception as e:
        print(f"[ERROR] Supabase connection failed: {e}")
else:
    print("[ERROR] Missing SUPABASE_URL or SUPABASE_KEY in .env")

# 2. Check MT5 Terminal Connection
try:
    if mt5.initialize():
        acc = mt5.account_info()
        if acc:
            print(f"[OK] MT5 Connected successfully. Account: {acc.login}, Balance: ${acc.balance:.2f}")
        else:
            print("[WARNING] MT5 initialized but account info unavailable. Check login.")
        mt5.shutdown()
    else:
        print(f"[ERROR] MT5 initialization failed: {mt5.last_error()}")
except Exception as e:
    print(f"[ERROR] MT5 check exception: {e}")

# 3. Check Binance Demo Futures Connection
api_key = os.getenv("BINANCE_DEMO_API_KEY")
secret = os.getenv("BINANCE_DEMO_SECRET")
if api_key and secret:
    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'options': {'defaultType': 'future'}
        })
        exchange.enable_demo_trading(True)
        exchange.fetch_balance()
        print("[OK] Binance Demo Futures connected successfully.")
    except Exception as e:
        print(f"[ERROR] Binance connection failed: {e}")
else:
    print("[WARNING] Binance API keys missing in .env (Crypto execution will be skipped)")

print("--- DIAGNOSTIC COMPLETE ---")