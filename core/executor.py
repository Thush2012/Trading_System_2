import logging
import os
import time
from datetime import UTC, datetime
from datetime import time as dt_time
import MetaTrader5 as mt5
import pytz
from dotenv import load_dotenv
from supabase import Client, create_client
from core.risk_manager import RiskManager

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("MT5_AutoExecutor")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MT5_ACCOUNT = int(os.getenv("MT5_ACCOUNT", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "")
MT5_PATH = os.getenv("MT5_PATH", "")
LOT_SIZE = 0.01
MAX_OPEN_POSITIONS = 2

# Daily Profit Target & Risk Caps (in USD)
DAILY_PROFIT_TARGET_USD = 4.00   # Locks in your daily target
DAILY_MAX_LOSS_CAP_USD = -3.00   # Stops trading for the day if down -$3.00

# Sri Lanka Time Window Configuration
LOCAL_TZ = pytz.timezone("Asia/Colombo")
WINDOW_START_HOUR = 13.5  # 1:30 PM SLT
WINDOW_END_HOUR = 21.5    # 9:30 PM SLT

risk_mgr = RiskManager()
highest_prices_tracker: dict[str, float] = {}

def is_execution_window_active() -> tuple[bool, str]:
    """Ensures orders only execute Mon-Fri between 1:30 PM and 9:30 PM SLT."""
    now = datetime.now(LOCAL_TZ)
    if now.weekday() >= 5:
        return False, "Weekend Standby (Saturday/Sunday)."
    current_decimal_hour = now.hour + (now.minute / 60.0)
    if not (WINDOW_START_HOUR <= current_decimal_hour <= WINDOW_END_HOUR):
        return False, f"Outside trading hours ({now.strftime('%I:%M %p')} SLT). Active: 1:30 PM - 9:30 PM."
    return True, "Window Active"

def check_daily_pnl_limits() -> tuple[bool, str, float]:
    """Calculates today's closed MT5 profit/loss and checks if daily target or max loss is reached."""
    now = datetime.now()
    start_of_day = datetime.combine(now.date(), dt_time.min)
    deals = mt5.history_deals_get(start_of_day, now)
    if deals is None:
        return True, "OK", 0.0
    daily_net = sum(
        deal.profit + deal.swap + deal.commission
        for deal in deals
        if deal.entry == mt5.DEAL_ENTRY_OUT
    )
    daily_net = round(daily_net, 2)
    if daily_net >= DAILY_PROFIT_TARGET_USD:
        return False, f"DAILY_TARGET_LOCKED (+${daily_net:.2f} banked today)", daily_net
    if daily_net <= DAILY_MAX_LOSS_CAP_USD:
        return False, f"DAILY_LOSS_LIMIT_HIT (${daily_net:.2f} today)", daily_net
    return True, "OK", daily_net

def resolve_filling_mode(symbol: str) -> int:
    """Detects broker-supported filling type to avoid retcode 10030 rejections."""
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
    """Connects to the active MT5 terminal using the path specified in .env or auto-detects."""
    if datetime.now(LOCAL_TZ).weekday() >= 5:
        log.info("Today is Saturday/Sunday. MT5 initialization skipped to respect weekend guard.")
        return False
    success = False
    if MT5_PATH:
        log.info(f"Initializing MT5 using path from .env: {MT5_PATH}")
        success = mt5.initialize(
            path=MT5_PATH,
            login=MT5_ACCOUNT if MT5_ACCOUNT else None,
            password=MT5_PASSWORD if MT5_PASSWORD else None,
            server=MT5_SERVER if MT5_SERVER else None
        )
    else:
        success = mt5.initialize()
        if success and MT5_ACCOUNT and MT5_PASSWORD and MT5_SERVER:
            mt5.login(login=MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER)
    if not success:
        log.error(f"MT5 terminal initialization failed: {mt5.last_error()}")
        return False
    t_info = mt5.terminal_info()
    if not t_info.trade_allowed:
        log.error("Algo Trading is OFF in MT5. Click the 'Algo Trading' button on the toolbar to turn it GREEN.")
        return False
    acc_info = mt5.account_info()
    if not acc_info or not acc_info.trade_allowed:
        log.error("Account trading disabled. Confirm login with Master Trading Password.")
        return False
    _, _, today_pnl = check_daily_pnl_limits()
    log.info(
        f"Connected to MT5 | Account: {acc_info.login} | Balance: ${acc_info.balance:.2f} | "
        f"Today's Closed PnL: ${today_pnl:.2f} (Target: +${DAILY_PROFIT_TARGET_USD:.2f})"
    )
    return True

def manage_active_mt5_positions_with_trailing_stop():
    """Active MT5 Break-Even and Dynamic Trailing Stop Engine"""
    try:
        positions = mt5.positions_get()
        if not positions:
            return
        for pos in positions:
            symbol = pos.symbol
            ticket = pos.ticket
            entry = pos.price_open
            sl = pos.sl
            tp = pos.tp
            is_buy = (pos.type == mt5.POSITION_TYPE_BUY)
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                continue
            current_price = tick.bid if is_buy else tick.ask
            sym_info = mt5.symbol_info(symbol)
            digits = sym_info.digits if sym_info else 5

            peak = highest_prices_tracker.get(symbol, entry)
            if is_buy:
                if current_price > peak:
                    peak = current_price
                    highest_prices_tracker[symbol] = peak
                profit_pct = (current_price - entry) / entry
                if profit_pct >= 0.006:
                    new_sl = peak * 0.995
                    if new_sl > sl and new_sl < current_price:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": ticket,
                            "sl": round(new_sl, digits),
                            "tp": round(tp, digits)
                        }
                        result = mt5.order_send(request)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            log.info(f"[MT5 Trailing] #{ticket} ({symbol}) trailing SL updated to: {new_sl:.5f}")
            else:
                if current_price < peak or peak == entry:
                    peak = current_price
                    highest_prices_tracker[symbol] = peak
                profit_pct = (entry - current_price) / entry
                if profit_pct >= 0.006:
                    new_sl = peak * 1.005
                    if (new_sl < sl or sl == 0.0) and new_sl > current_price:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": ticket,
                            "sl": round(new_sl, digits),
                            "tp": round(tp, digits)
                        }
                        result = mt5.order_send(request)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            log.info(f"[MT5 Trailing] #{ticket} ({symbol}) short trailing SL updated to: {new_sl:.5f}")
    except Exception as e:
        log.error(f"Error in MT5 trailing stop manager: {e}")

def process_trade_signal(sig: dict) -> tuple[bool, str | int]:
    allowed, window_msg = is_execution_window_active()
    if not allowed:
        log.warning(f"Skipped execution: {window_msg}")
        return False, f"WINDOW_LOCK: {window_msg}"
        
    pnl_allowed, pnl_reason, current_pnl = check_daily_pnl_limits()
    if not pnl_allowed:
        log.info(f"Trade skipped: {pnl_reason}")
        return False, pnl_reason
        
    raw_symbol = sig["symbol"]
    
    # Cooldown check integration
    on_cd, cd_msg = risk_mgr.is_symbol_on_cooldown(raw_symbol)
    if on_cd:
        log.warning(f"Trade rejected on {raw_symbol}: {cd_msg}")
        return False, f"COOLDOWN_ACTIVE: {cd_msg}"

    broker_symbol = f"{raw_symbol}{SYMBOL_SUFFIX}"
    if not mt5.symbol_select(broker_symbol, True):
        log.error(f"Symbol {broker_symbol} not found in Market Watch.")
        return False, "SYMBOL_NOT_FOUND"
        
    sym_info = mt5.symbol_info(broker_symbol)
    if not sym_info:
        return False, "SYMBOL_INFO_UNAVAILABLE"
        
    pair_positions = mt5.positions_get(symbol=broker_symbol)
    if pair_positions and len(pair_positions) > 0:
        log.warning(f"Position already active on {broker_symbol}. Skipping duplicate.")
        return False, "DUPLICATE_POSITION"
        
    total_positions = mt5.positions_get()
    if total_positions and len(total_positions) >= MAX_OPEN_POSITIONS:
        log.warning(f"Max concurrent open positions reached ({len(total_positions)}/{MAX_OPEN_POSITIONS}).")
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
    
    # Dynamic lot size calculation via RiskManager
    acc_info = mt5.account_info()
    balance = acc_info.balance if acc_info else 100.0
    dynamic_lot = risk_mgr.calculate_forex_lot_size(balance, entry_price, sl)

    order_payload = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": broker_symbol,
        "volume": dynamic_lot,
        "type": order_type,
        "price": entry_price,
        "sl": sl,
        "tp": tp,
        "deviation": 25,
        "magic": 992026,
        "comment": f"AutoSignal_{sig.get('setup', '1.6R')}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": resolve_filling_mode(broker_symbol),
    }
    result = mt5.order_send(order_payload)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(
            f"Order executed: #{result.order} {broker_symbol} {direction} @ {entry_price} | "
            f"Lots: {dynamic_lot} | SL: {sl} | TP: {tp} | Today PnL: ${current_pnl:.2f}"
        )
        return True, result.order
    else:
        retcode = result.retcode if result else "UNKNOWN"
        comment = result.comment if result else "No response"
        log.error(f"Order rejected on {broker_symbol}: Retcode {retcode} ({comment})")
        return False, f"RETCODE_{retcode}: {comment}"

def run_executor():
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("Missing SUPABASE_URL or SUPABASE_KEY in local .env.")
        return
        
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    if not initialize_terminal():
        return
        
    log.info(
        f"Executor polling Supabase | Window: 1:30 PM - 9:30 PM SLT | "
        f"Daily Target Lock: +${DAILY_PROFIT_TARGET_USD:.2f}"
    )
    while True:
        try:
            if datetime.now(LOCAL_TZ).weekday() >= 5:
                time.sleep(60)
                continue
                
            # Manage active positions & trailing stops
            manage_active_mt5_positions_with_trailing_stop()

            query = (
                supabase.table("trade_signals")
                .select("*")
                .eq("status", "PENDING")
                .order("created_at")
                .limit(1)
                .execute()
            )
            pending_batch = query.data
            if pending_batch:
                for sig in pending_batch:
                    sig_id = sig["id"]
                    
                    # Atomic claim / status update
                    lock_res = (
                        supabase.table("trade_signals")
                        .update({"status": "LOCKED"})
                        .eq("id", sig_id)
                        .eq("status", "PENDING")
                        .execute()
                    )
                    if not lock_res.data:
                        continue

                    # STALE SIGNAL CHECK: Auto-expire signals older than 10 minutes
                    try:
                        created_at = datetime.fromisoformat(sig["created_at"].replace("Z", "+00:00"))
                        if (datetime.now(UTC) - created_at).total_seconds() > 600:
                            supabase.table("trade_signals").update({"status": "EXPIRED", "error_message": "STALE_SIGNAL (>600s)"}).eq("id", sig_id).execute()
                            log.warning(f"Expired stale signal {sig_id} from queue.")
                            continue
                    except Exception:
                        pass

                    log.info(f"Processing signal #{sig_id}: {sig['symbol']} {sig['action']}")
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

class ExecutionEngine:
    """Compatibility wrapper class for live engine and type checking imports."""
    @staticmethod
    def run() -> None:
        run_executor()

if __name__ == "__main__":
    run_executor()