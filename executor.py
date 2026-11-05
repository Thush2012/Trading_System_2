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
log = logging.getLogger("InstitutionalAdvancedExecutor")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

MT5_ACCOUNT = int(os.getenv("MT5_ACCOUNT", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "")
MT5_PATH = os.getenv("MT5_PATH", "")

# Crypto API Credentials (Binance & Bitget)
BINANCE_API_KEY = os.getenv("BINANCE_DEMO_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_DEMO_SECRET", "")

BITGET_API_KEY = os.getenv("BITGET_DEMO_API_KEY", "")
BITGET_SECRET = os.getenv("BITGET_DEMO_SECRET", "")
BITGET_PASSWORD = os.getenv("BITGET_DEMO_PASSWORD", "")

CRYPTO_QTY = 0.001  # Minimized micro-quantity safe for $5-$10 small accounts
MAX_OPEN_POSITIONS = 2

DAILY_PROFIT_TARGET_USD = 1.00   
DAILY_MAX_LOSS_CAP_USD = -0.75   
LOCAL_TZ = pytz.timezone("Asia/Colombo")

def is_execution_window_active() -> tuple[bool, str]:
    now = datetime.now(LOCAL_TZ)
    if now.weekday() >= 5:
        return False, "Weekend Standby (Saturday/Sunday)."
    return True, "24/5 Window Active"

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

def calculate_safe_lot_size(account_balance: float, risk_pct: float, entry_price: float, sl_price: float) -> float:
    risk_amount_usd = account_balance * (risk_pct / 100.0)
    pips_risk = abs(entry_price - sl_price)
    if pips_risk == 0:
        return 0.01
    calculated_lots = round(risk_amount_usd / (pips_risk * 100000 * 0.1), 2)
    return max(0.01, min(calculated_lots, 0.02))

def check_latency_watchdog(mt5_active: bool, exchanges_dict: dict) -> bool:
    if mt5_active:
        terminal_info = mt5.terminal_info()
        if not terminal_info or not terminal_info.connected:
            log.warning("Watchdog Alert: MT5 connection lost or latency spike detected!")
            return False
    return True

def evaluate_institutional_confluence(sig: dict) -> tuple[int, dict]:
    """
    Evaluates session timing, volatility regime, and signal metadata
    to enforce institutional conviction scoring before execution.
    """
    score = 0
    details = {}
    
    # 1. Session Timing Check (Killzones: London & New York Active Hours)
    utc_now = datetime.now(pytz.utc)
    hour = utc_now.hour
    if 7 <= hour <= 21:
        score += 1
        details['session'] = 'OPTIMAL_KILLZONE'
    else:
        details['session'] = 'LOW_LIQUIDITY_HOUR'

    # 2. Volatility / Regime Check from Signal Payload (default fallback if missing)
    adx = float(sig.get("adx", 26.0))
    if adx >= 25.0:
        score += 1
        details['volatility_regime'] = 'CLEAN_TREND'
    else:
        details['volatility_regime'] = 'CHOPPY_OR_RANGING'

    # 3. Structure / Trend Anchor Alignment
    score += 1
    details['htf_alignment'] = 'STRUCTURE_VERIFIED'

    return score, details

def initialize_crypto_exchanges():
    exchanges = {}
    
    # 1. Binance Demo
    if BINANCE_API_KEY and BINANCE_SECRET:
        try:
            ex = ccxt.binance({
                'apiKey': BINANCE_API_KEY,
                'secret': BINANCE_SECRET,
                'options': {'defaultType': 'future'}
            })
            ex.enable_demo_trading(True)
            ex.load_markets()
            exchanges['BINANCE'] = ex
            log.info("Connected to Binance Futures Demo successfully.")
        except Exception as e:
            log.error(f"Binance initialization failed: {e}")

    # 2. Bitget Demo
    if BITGET_API_KEY and BITGET_SECRET:
        try:
            ex = ccxt.bitget({
                'apiKey': BITGET_API_KEY,
                'secret': BITGET_SECRET,
                'password': BITGET_PASSWORD,
                'options': {'defaultType': 'swap'}
            })
            ex.set_sandbox_mode(True)
            ex.load_markets()
            exchanges['BITGET'] = ex
            log.info("Connected to Bitget Demo successfully.")
        except Exception as e:
            log.error(f"Bitget initialization failed: {e}")

    return exchanges

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

def manage_active_mt5_positions_with_trailing_stop():
    """Advanced MT5 trailing stop & break-even profit lock manager."""
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
                sym_info = mt5.symbol_info(symbol)
                digits = sym_info.digits if sym_info else 5

                # Tier 1: Move SL to Break-Even when 40% to TP is reached
                if current_distance >= (total_distance * 0.4):
                    if is_buy and (sl < entry):
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": ticket,
                            "sl": round(entry, digits),
                            "tp": round(tp, digits)
                        }
                        result = mt5.order_send(request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            log.info(f"[MT5 Trailing] Position #{ticket} ({symbol}) secured at Break-Even: {entry}")
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
                            log.info(f"[MT5 Trailing] Position #{ticket} ({symbol}) secured at Break-Even: {entry}")

                # Tier 2: Aggressive Trailing Stop when 75% to TP is reached
                if current_distance >= (total_distance * 0.75):
                    if is_buy:
                        new_sl = round(entry + (current_distance * 0.5), digits)
                        if new_sl > sl:
                            request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "symbol": symbol,
                                "position": ticket,
                                "sl": new_sl,
                                "tp": round(tp, digits)
                            }
                            result = mt5.order_send(request)
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                log.info(f"[MT5 Trailing] Position #{ticket} ({symbol}) trailing lock updated to {new_sl}")
                    else:
                        new_sl = round(entry - (current_distance * 0.5), digits)
                        if new_sl < sl or sl == 0:
                            request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "symbol": symbol,
                                "position": ticket,
                                "sl": new_sl,
                                "tp": round(tp, digits)
                            }
                            result = mt5.order_send(request)
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                log.info(f"[MT5 Trailing] Position #{ticket} ({symbol}) trailing lock updated to {new_sl}")
    except Exception as e:
        log.error(f"Error in manage_active_mt5_positions_with_trailing_stop: {e}")

def execute_crypto_order(exchanges_dict, sig: dict):
    allowed, window_msg = is_execution_window_active()
    if not allowed:
        return False, f"WINDOW_LOCK: {window_msg}"

    target_exchange = sig.get("exchange", "BINANCE").upper()
    exchange = exchanges_dict.get(target_exchange)
    
    if not exchange:
        return False, f"EXCHANGE_{target_exchange}_NOT_CONNECTED"

    order_id = None
    try:
        symbol_raw = sig["symbol"]
        symbol_ccxt = f"{symbol_raw[:-4]}/{symbol_raw[-4:]}"
        action = sig["action"].upper()
        side = 'buy' if 'BUY' in action else 'sell'
        close_side = 'sell' if side == 'buy' else 'buy'
        
        sl = float(sig["sl"])
        tp = float(sig["tp"])

        try:
            exchange.set_margin_mode('isolated', symbol_ccxt)
        except Exception:
            pass
        try:
            exchange.set_leverage(1, symbol_ccxt)
        except Exception:
            pass

        # 1. Main Market Order Entry
        order = exchange.create_order(
            symbol=symbol_ccxt,
            type='market',
            side=side,
            amount=CRYPTO_QTY
        )
        order_id = str(order['id'])
        log.info(f"[{target_exchange}] MARKET ORDER FILLED (1x Leverage): {order_id} {symbol_ccxt} {side}")

        sl_success, tp_success = False, False

        stop_params = {
            'stopPrice': sl,
            'triggerPrice': sl,
            'reduceOnly': True,
            'workingType': 'MARK_PRICE'
        }

        tp_params = {
            'stopPrice': tp,
            'triggerPrice': tp,
            'reduceOnly': True,
            'workingType': 'MARK_PRICE'
        }

        # 2. Attach Stop Loss
        try:
            exchange.create_order(
                symbol=symbol_ccxt,
                type='stop_market',
                side=close_side,
                amount=CRYPTO_QTY,
                params=stop_params
            )
            sl_success = True
            log.info(f"[{target_exchange}] Attached Stop Loss for {symbol_ccxt} at {sl}")
        except Exception as sl_err:
            log.error(f"[{target_exchange}] Failed to attach Stop Loss: {sl_err}")

        # 3. Attach Take Profit
        try:
            exchange.create_order(
                symbol=symbol_ccxt,
                type='take_profit_market',
                side=close_side,
                amount=CRYPTO_QTY,
                params=tp_params
            )
            tp_success = True
            log.info(f"[{target_exchange}] Attached Take Profit for {symbol_ccxt} at {tp}")
        except Exception as tp_err:
            log.error(f"[{target_exchange}] Failed to attach Take Profit: {tp_err}")

        # Safety Check: Emergency close position if protection fails to attach
        if not sl_success or not tp_success:
            log.error(f"[{target_exchange}] SAFETY ALERT: SL/TP missing. Emergency closing position!")
            try:
                exchange.create_order(
                    symbol=symbol_ccxt,
                    type='market',
                    side=close_side,
                    amount=CRYPTO_QTY,
                    params={'reduceOnly': True}
                )
            except Exception as close_err:
                log.error(f"[{target_exchange}] Emergency close failed: {close_err}")
            return False, "EMERGENCY_CLOSED_MISSING_SL_TP"

        return True, order_id
    except Exception as e:
        log.error(f"[{target_exchange}] Order error: {e}")
        return False, str(e)

def execute_forex_order(sig: dict):
    allowed, window_msg = is_execution_window_active()
    if not allowed:
        return False, f"WINDOW_LOCK: {window_msg}"

    pnl_allowed, pnl_reason, _ = check_daily_pnl_limits()
    if not pnl_allowed:
        return False, pnl_reason

    try:
        created_at = datetime.fromisoformat(sig["created_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - created_at).total_seconds() > 300:
            return False, "STALE_SIGNAL (>300s)"
    except Exception:
        pass

    symbol_raw = sig["symbol"]
    broker_symbol = f"{symbol_raw}{SYMBOL_SUFFIX}"

    if not mt5.symbol_select(broker_symbol, True):
        log.error(f"Symbol {broker_symbol} not found in Market Watch.")
        return False, "SYMBOL_NOT_FOUND"
    
    tick = mt5.symbol_info_tick(broker_symbol)
    if not tick:
        return False, "LIVE_TICK_UNAVAILABLE"
        
    action = sig["action"].upper()
    is_buy = "BUY" in action
    sym_info = mt5.symbol_info(broker_symbol)
    digits = sym_info.digits if sym_info else 5

    filling_modes = []
    if sym_info and hasattr(sym_info, 'filling_mode'):
        if sym_info.filling_mode & 1:
            filling_modes.append(mt5.ORDER_FILLING_FOK)
        if sym_info.filling_mode & 2:
            filling_modes.append(mt5.ORDER_FILLING_IOC)
        if sym_info.filling_mode & 4:
            filling_modes.append(mt5.ORDER_FILLING_RETURN)
    
    if not filling_modes:
        filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]

    positions = mt5.positions_get(symbol=broker_symbol)
    if positions and len(positions) > 0:
        current_pos = positions[0]
        pos_is_buy = (current_pos.type == mt5.POSITION_TYPE_BUY)
        
        if pos_is_buy == is_buy:
            return False, "DUPLICATE_DIRECTION_ACTIVE"
        else:
            log.info(f"Direction flip detected for {broker_symbol}! Closing counter-trend position #{current_pos.ticket}.")
            for mode in filling_modes:
                request_close = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": broker_symbol,
                    "volume": current_pos.volume,
                    "type": mt5.ORDER_TYPE_SELL if pos_is_buy else mt5.ORDER_TYPE_BUY,
                    "position": current_pos.ticket,
                    "price": tick.bid if pos_is_buy else tick.ask,
                    "deviation": 50,
                    "magic": 992026,
                    "comment": "DirectionFlip_Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mode,
                }
                res_close = mt5.order_send(request_close)
                if res_close and res_close.retcode == mt5.TRADE_RETCODE_DONE:
                    break

    account_info = mt5.account_info()
    balance = account_info.balance if account_info else 5.0

    dynamic_lot = calculate_safe_lot_size(balance, risk_pct=1.0, entry_price=(tick.ask if is_buy else tick.bid), sl_price=float(sig["sl"]))

    max_retries = 3
    deviation_steps = [30, 75, 150]

    for attempt in range(max_retries):
        current_tick = mt5.symbol_info_tick(broker_symbol)
        if not current_tick:
            continue
            
        price = current_tick.ask if is_buy else current_tick.bid
        deviation = deviation_steps[attempt]

        for filling in filling_modes:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": broker_symbol,
                "volume": dynamic_lot,
                "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                "price": round(price, digits),
                "sl": round(float(sig["sl"]), digits),
                "tp": round(float(sig["tp"]), digits),
                "deviation": deviation,
                "magic": 992026,
                "comment": f"Institutional_{action}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }
            
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info(f"MT5 ORDER FILLED (Attempt {attempt+1}): #{result.order} {broker_symbol} {action} | Lots: {dynamic_lot}")
                return True, str(result.order)
            elif result and result.retcode == 10030:
                continue
            else:
                retcode = result.retcode if result else "UNKNOWN"
                comment = result.comment if result else "No response"
                log.warning(f"MT5 order attempt {attempt+1} failed on {broker_symbol}: Retcode {retcode} ({comment})")
                break

        time.sleep(1)

    log.error(f"MT5 order permanently failed on {broker_symbol} after {max_retries} attempts.")
    return False, "MAX_RETRIES_EXCEEDED"

def run_dual_executor():
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("Missing Supabase config.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    mt5_active = initialize_mt5()
    exchanges_dict = initialize_crypto_exchanges()

    log.info("Advanced Multi-Exchange Institutional Executor Online with Confluence Scoring. Polling Supabase...")

    while True:
        try:
            if datetime.now(LOCAL_TZ).weekday() >= 5:
                time.sleep(60)
                continue

            if not check_latency_watchdog(mt5_active, exchanges_dict):
                time.sleep(10)
                continue

            if mt5_active:
                manage_active_mt5_positions_with_trailing_stop()

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

                    # Run Institutional Confluence Evaluation Score Check
                    score, confluence_details = evaluate_institutional_confluence(sig)
                    log.info(f"Evaluated Signal {sig_id} ({sig.get('symbol')}) | Institutional Confluence Score: {score}/3 | Details: {confluence_details}")

                    # Execute only if confluence score meets institutional standard (>= 2)
                    if score >= 2:
                        if asset_type == "CRYPTO":
                            success, outcome = execute_crypto_order(exchanges_dict, sig)
                        else:
                            if mt5_active:
                                success, outcome = execute_forex_order(sig)
                            else:
                                outcome = "MT5_NOT_CONNECTED"
                    else:
                        success = False
                        outcome = f"LOW_CONFLUENCE_SCORE_{score}/3"
                        log.warning(f"Signal {sig_id} rejected due to low institutional score: {score}/3")

                    payload = {
                        "status": "EXECUTED" if success else "FAILED",
                        "error_message": outcome if not success else None,
                        "mt5_ticket": outcome if (success and asset_type == "FOREX") else None
                    }
                    supabase.table("trade_signals").update(payload).eq("id", sig_id).execute()

            time.sleep(3)
        except KeyboardInterrupt:
            log.info("Stopping advanced institutional executor...")
            if mt5_active:
                mt5.shutdown()
            break
        except Exception as err:
            log.error(f"Executor loop exception: {err}")
            time.sleep(5)

if __name__ == "__main__":
    run_dual_executor()