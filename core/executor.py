import os
import time
import logging
from datetime import datetime
import pytz
from dotenv import load_dotenv
from supabase import create_client, Client
import MetaTrader5 as mt5

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("MT5_AutoExecutor")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MT5_ACCOUNT = int(os.getenv("MT5_ACCOUNT", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "")

LOT_SIZE = 0.01
MAX_OPEN_POSITIONS = 2

# Sri Lanka Time Window Configuration
LOCAL_TZ = pytz.timezone("Asia/Colombo")
WINDOW_START_HOUR = 13.5  # 1:30 PM
WINDOW_END_HOUR = 21.5    # 9:30 PM

def is_execution_window_active() -> tuple[bool, str]:
    """Ensures orders only execute Mon-Fri between 1:30 PM and 9:30 PM SLT."""
    now = datetime.now(LOCAL_TZ)
    # Check Weekend: Monday=0, Sunday=6
    if now.weekday() >= 5:
        return False, "Market closed for weekend (Saturday/Sunday)."

    current_decimal_hour = now.hour + (now.minute / 60.0)
    if not (WINDOW_START_HOUR <= current_decimal_hour <= WINDOW_END_HOUR):
        return False, f"Outside execution window (Current: {now.strftime('%I:%M %p')}, Active: 1:30 PM - 9:30 PM SLT)."

    return True, "Window Active"

def resolve_filling_mode(symbol: str) -> int:
    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        return mt5.ORDER_FILLING_IOC
    modes = sym_info.filling_mode
    if modes & 2:
        return mt5.ORDER_FILLING_IOC
    elif modes & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN

def initialize_terminal() -> bool:
    if not mt5.initialize():
        log.error(f"MT5 terminal initialization failed: {mt5.last_error()}")
        return False

    if MT5_ACCOUNT and MT5_PASSWORD and MT5_SERVER:
        current_acc = mt5.account_info()
        if not current_acc or current_acc.login != MT5_ACCOUNT:
            authorized = mt5.login(login=MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER)
            if not authorized:
                log.error(f"Failed to log into MT5 account #{MT5_ACCOUNT}: {mt5.last_error()}")
                return False

    t_info = mt5.terminal_info()
    if not t_info.trade_allowed:
        log.error("Algorithmic Trading is toggled OFF. Ensure 'Algo Trading' toolbar button is GREEN.")
        return False

    acc_info = mt5.account_info()
    if not acc_info or not acc_info.trade_allowed:
        log.error("Account trading disabled. Confirm login with Master Trading Password.")
        return False

    log.info(f"Connected to MT5 | Account: {acc_info.login} ({acc_info.company}) | Balance: ${acc_info.balance:.2f}")
    return True

def process_trade_signal(sig: dict) -> tuple[bool, str | int]:
    # 1. Enforce Trading Hours & Weekend Guard
    allowed, window_msg = is_execution_window_active()
    if not allowed:
        log.warning(f"Trade rejected by window guard: {window_msg}")
        return False, f"WINDOW_RESTRICTION: {window_msg}"

    raw_symbol = sig["symbol"]
    broker_symbol = f"{raw_symbol}{SYMBOL_SUFFIX}"

    if not mt5.symbol_select(broker_symbol, True):
        log.error(f"Symbol {broker_symbol} not found in Market Watch.")
        return False, "SYMBOL_NOT_FOUND"

    sym_info = mt5.symbol_info(broker_symbol)
    if not sym_info:
        return False, "SYMBOL_INFO_UNAVAILABLE"

    pair_positions = mt5.positions_get(symbol=broker_symbol)
    if pair_positions and len(pair_positions) > 0:
        log.warning(f"Position already active on {broker_symbol}. Skipping.")
        return False, "DUPLICATE_POSITION"

    total_positions = mt5.positions_get()
    if total_positions and len(total_positions) >= MAX_OPEN_POSITIONS:
        log.warning(f"Maximum concurrent open positions reached ({len(total_positions)}/{MAX_OPEN_POSITIONS}).")
        return False, "MAX_POSITIONS_REACHED"

    tick = mt5.symbol_info_tick(broker_symbol)
    if not tick:
        return False, "LIVE_TICK_UNAVAILABLE"

    direction = sig["action"].upper()
    is_buy = "BUY" in direction
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    digits = sym_info.digits

    entry_price = round(tick.ask if is_buy else tick.bid, digits)
    sl = round(float(sig["sl"]), digits)
    tp = round(float(sig.get("tp", sig.get("tp1", 0.0))), digits)

    order_payload = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": broker_symbol,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": entry_price,
        "sl": sl,
        "tp": tp,
        "deviation": 25,
        "magic": 992026,
        "comment": "AutoSignal Engine",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": resolve_filling_mode(broker_symbol),
    }

    result = mt5.order_send(order_payload)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"Order filled: #{result.order} {broker_symbol} {direction} @ {entry_price} | SL: {sl} | TP: {tp}")
        return True, result.order
    else:
        log.error(f"Order rejected on {broker_symbol}: Retcode {result.retcode} ({result.comment})")
        return False, f"RETCODE_{result.retcode}: {result.comment}"

def run_executor():
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("Missing SUPABASE_URL or SUPABASE_KEY in local .env.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    if not initialize_terminal():
        return

    log.info("MT5 Local Executor active. Polling Supabase (1:30 PM - 9:30 PM SLT Execution Guard active)...")

    while True:
        try:
            # Query oldest pending signal
            query = supabase.table("trade_signals").select("*").eq("status", "PENDING").order("created_at").limit(1).execute()
            pending_batch = query.data

            if pending_batch:
                for sig in pending_batch:
                    sig_id = sig["id"]
                    log.info(f"Processing trade signal #{sig_id}: {sig['symbol']} {sig['action']}")
                    success, outcome = process_trade_signal(sig)

                    status_str = "EXECUTED" if success else "FAILED"
                    payload = {"status": status_str}
                    if success:
                        payload["mt5_ticket"] = outcome
                    else:
                        payload["error_message"] = str(outcome)

                    supabase.table("trade_signals").update(payload).eq("id", sig_id).execute()

            time.sleep(3)
        except KeyboardInterrupt:
            log.info("Stopping executor...")
            mt5.shutdown()
            break
        except Exception as err:
            log.error(f"Execution loop exception: {err}")
            time.sleep(5)

if __name__ == "__main__":
    run_executor()