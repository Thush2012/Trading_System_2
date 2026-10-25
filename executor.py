import os
import time
import logging
from datetime import datetime, time as dt_time, timezone
import pytz
from dotenv import load_dotenv
from supabase import create_client, Client
import MetaTrader5 as mt5
import ccxt

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("DualAssetExecutor")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# MT5 Details (Forex)
MT5_ACCOUNT = int(os.getenv("MT5_ACCOUNT", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "")
MT5_PATH = os.getenv("MT5_PATH", "")

# Binance Demo Details (Crypto)
BINANCE_API_KEY = os.getenv("BINANCE_DEMO_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_DEMO_SECRET", "")

LOT_SIZE_FOREX = 0.01
CRYPTO_QTY = 0.005  # Position size for BTC/ETH futures demo
MAX_OPEN_POSITIONS = 2

DAILY_PROFIT_TARGET_USD = 4.00
DAILY_MAX_LOSS_CAP_USD = -3.00

LOCAL_TZ = pytz.timezone("Asia/Colombo")

def is_execution_window_active() -> tuple[bool, str]:
    """Ensures orders execute Mon-Fri from 8:00 AM to 9:30 PM SLT, blocking 6:30-8:30 PM power cut."""
    now = datetime.now(LOCAL_TZ)
    if now.weekday() >= 5:
        return False, "Weekend Standby (Saturday/Sunday)."

    current_decimal_hour = now.hour + (now.minute / 60.0)
    is_in_span = 8.0 <= current_decimal_hour <= 21.5
    is_power_cut = 18.5 <= current_decimal_hour <= 20.5

    if not is_in_span:
        return False, f"Outside trading hours ({now.strftime('%I:%M %p')} SLT)."
    if is_power_cut:
        return False, "Power cut blackout active (6:30 PM - 8:30 PM SLT)."

    return True, "Window Active"

def check_daily_pnl_limits() -> tuple[bool, str, float]:
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
        return False, f"DAILY_TARGET_LOCKED (+${daily_net:.2f})", daily_net
    if daily_net <= DAILY_MAX_LOSS_CAP_USD:
        return False, f"DAILY_LOSS_LIMIT_HIT (${daily_net:.2f})", daily_net

    return True, "OK", daily_net

def initialize_binance():
    """Initializes CCXT for Binance USDⓈ-M Futures Demo Trading."""
    if not BINANCE_API_KEY or not BINANCE_SECRET:
        log.warning("Binance API keys missing in .env. Crypto execution skipped.")
        return None
    try:
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_SECRET,
            'options': {'defaultType': 'future'}
        })
        exchange.enable_demo_trading(True)  # Switch to Binance Demo Trading mode
        exchange.load_markets()
        log.info("Connected to Binance Futures Demo Trading successfully.")
        return exchange
    except Exception as e:
        log.error(f"Binance initialization failed: {e}")
        return None

def initialize_mt5() -> bool:
    if datetime.now(LOCAL_TZ).weekday() >= 5:
        log.info("Weekend guard active. MT5 initialization skipped.")
        return False

    success = False
    if MT5_PATH:
        success = mt5.initialize(path=MT5_PATH, login=MT5_ACCOUNT or None, password=MT5_PASSWORD or None, server=MT5_SERVER or None)
    else:
        success = mt5.initialize()
        if success and MT5_ACCOUNT and MT5_PASSWORD and MT5_SERVER:
            mt5.login(login=MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER)

    if not success:
        log.error(f"MT5 initialization failed: {mt5.last_error()}")
        return False

    if not mt5.terminal_info().trade_allowed:
        log.error("Algo Trading is DISABLED in MT5.")
        return False

    log.info(f"MT5 Connected | Account: {mt5.account_info().login} | Balance: ${mt5.account_info().balance:.2f}")
    return True

def manage_active_mt5_positions():
    """Autonomously monitors open MT5 positions and moves SL to break-even when 50% toward TP1."""
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

            if tp > 0:
                total_distance = abs(tp - entry)
                current_distance = abs(current_price - entry)

                # If price reaches 50% towards Take Profit, shift SL to entry (Break-Even)
                if current_distance >= (total_distance * 0.5):
                    sym_info = mt5.symbol_info(symbol)
                    digits = sym_info.digits if sym_info else 5

                    if is_buy and sl < entry:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": ticket,
                            "sl": round(entry, digits),
                            "tp": round(tp, digits)
                        }
                        result = mt5.order_send(request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            log.info(f"AUTO BREAK-EVEN: MT5 Position #{ticket} ({symbol}) SL moved to entry price {entry}")
                    elif not is_buy and (sl > entry or sl == 0):
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": ticket,
                            "sl": round(entry, digits),
                            "tp": round(tp, digits)
                        }
                        result = mt5.order_send(request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            log.info(f"AUTO BREAK-EVEN: MT5 Position #{ticket} ({symbol}) SL moved to entry price {entry}")
    except Exception as e:
        log.error(f"Error in manage_active_mt5_positions: {e}")

def execute_crypto_order(exchange, sig: dict):
    """Executes crypto futures orders on Binance Demo via CCXT."""
    allowed, window_msg = is_execution_window_active()
    if not allowed:
        return False, f"WINDOW_LOCK: {window_msg}"

    try:
        symbol_raw = sig["symbol"]  # e.g., BTCUSDT
        symbol_ccxt = f"{symbol_raw[:-4]}/{symbol_raw[-4:]}"
        action = sig["action"].upper()
        side = 'buy' if 'BUY' in action else 'sell'
        
        order = exchange.create_order(
            symbol=symbol_ccxt,
            type='market',
            side=side,
            amount=CRYPTO_QTY
        )
        log.info(f"BINANCE DEMO ORDER FILLED: {order['id']} {symbol_ccxt} {side}")
        return True, order['id']
    except Exception as e:
        log.error(f"Binance order error: {e}")
        return False, str(e)

def execute_forex_order(sig: dict):
    """Executes forex orders on MT5."""
    allowed, window_msg = is_execution_window_active()
    if not allowed:
        return False, f"WINDOW_LOCK: {window_msg}"

    pnl_allowed, pnl_reason, _ = check_daily_pnl_limits()
    if not pnl_allowed:
        return False, pnl_reason

    # Stale Signal Protection: Reject signals older than 90 seconds
    try:
        created_at = datetime.fromisoformat(sig["created_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - created_at).total_seconds() > 90:
            return False, "STALE_SIGNAL (>90s)"
    except Exception:
        pass

    symbol = f"{sig['symbol']}{SYMBOL_SUFFIX}"
    if not mt5.symbol_select(symbol, True):
        return False, "SYMBOL_NOT_FOUND"
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False, "LIVE_TICK_UNAVAILABLE"
        
    is_buy = "BUY" in sig["action"].upper()
    price = tick.ask if is_buy else tick.bid
    sym_info = mt5.symbol_info(symbol)
    digits = sym_info.digits if sym_info else 5

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": LOT_SIZE_FOREX,
        "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
        "price": round(price, digits),
        "sl": round(float(sig["sl"]), digits),
        "tp": round(float(sig["tp"]), digits),
        "deviation": 50,
        "magic": 992026,
        "comment": "DualAssetEngine",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"MT5 ORDER FILLED: #{result.order} {symbol}")
        return True, result.order
    return False, f"RETCODE_{result.retcode}"

def run_dual_executor():
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("Missing Supabase config.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    mt5_active = initialize_mt5()
    binance_exchange = initialize_binance()

    log.info("Dual-Asset Local Executor active with Break-Even Manager. Polling Supabase...")

    while True:
        try:
            if datetime.now(LOCAL_TZ).weekday() >= 5:
                time.sleep(60)
                continue

            # 1. Manage active position trailing/break-even checks
            if mt5_active:
                manage_active_mt5_positions()

            # 2. Poll Supabase for pending trade signals
            res = (
                supabase.table("trade_signals")
                .select("*")
                .eq("status", "PENDING")
                .order("created_at")
                .limit(1)
                .execute()
            )
            signals = res.data

            if signals:
                for sig in signals:
                    sig_id = sig["id"]
                    asset_type = sig.get("asset_type", "FOREX").upper()
                    success, outcome = False, ""

                    if asset_type == "CRYPTO":
                        if binance_exchange:
                            success, outcome = execute_crypto_order(binance_exchange, sig)
                        else:
                            outcome = "BINANCE_NOT_CONNECTED"
                    else:
                        if mt5_active:
                            success, outcome = execute_forex_order(sig)
                        else:
                            outcome = "MT5_NOT_CONNECTED"

                    payload = {
                        "status": "EXECUTED" if success else "FAILED",
                        "mt5_ticket" if asset_type == "FOREX" else "error_message": outcome
                    }
                    supabase.table("trade_signals").update(payload).eq("id", sig_id).execute()

            time.sleep(3)
        except KeyboardInterrupt:
            log.info("Stopping dual executor...")
            if mt5_active:
                mt5.shutdown()
            break
        except Exception as err:
            log.error(f"Executor loop exception: {err}")
            time.sleep(5)

if __name__ == "__main__":
    run_dual_executor()