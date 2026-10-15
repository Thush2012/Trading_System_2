import logging
import yfinance as yf
from datetime import datetime, timezone
from core.logger import setup_system_logger
from core.loss_memory import LossMemoryEngine

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

log = setup_system_logger("TradeTracker")
memory_engine = LossMemoryEngine()

class TradeTracker:
    def __init__(self):
        self.active_trades = {}

    def register_trade(self, signal_dict: dict, ticker: str):
        symbol = signal_dict["symbol"]
        action = signal_dict["action"]
        entry = float(signal_dict.get("current_price", signal_dict.get("entry_low", 0.0)))
        sl = float(signal_dict["sl"])
        tp1 = float(signal_dict.get("tp1", signal_dict.get("tp", 0.0)))
        tp2 = float(signal_dict.get("tp2", tp1))
        tp3 = float(signal_dict.get("tp3", tp2))

        self.active_trades[symbol] = {
            "symbol": symbol,
            "action": action,
            "entry_price": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "ticker": ticker,
            "adx": float(signal_dict.get("adx", 25.0)),
            "atr": float(signal_dict.get("atr", 0.0010)),
            "tp1_hit": False,
            "tp2_hit": False,
            "registered_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }
        log.info(f"Registered trade for tracking: {symbol} ({action}) @ {entry}")

    def fetch_current_price(self, symbol: str, ticker: str) -> float:
        if MT5_AVAILABLE:
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick and tick.bid > 0:
                    return float(tick.bid)
            except Exception:
                pass

        try:
            df = yf.download(ticker, period="1d", interval="1m", progress=False)
            if not df.empty:
                if isinstance(df.columns, object) and hasattr(df.columns, "get_level_values"):
                    df.columns = df.columns.get_level_values(0)
                return float(df["Close"].iloc[-1])
        except Exception as e:
            log.error(f"Price fetch error for {symbol}: {e}")
        return None

    def evaluate_active_trades(self) -> list:
        outcome_events = []
        completed_symbols = []

        for symbol, trade in list(self.active_trades.items()):
            current_price = self.fetch_current_price(symbol, trade["ticker"])
            if current_price is None:
                continue

            action = trade["action"]
            sl = trade["sl"]
            tp1 = trade["tp1"]
            tp2 = trade["tp2"]
            tp3 = trade["tp3"]
            is_buy = "BUY" in action

            # 1. Stop Loss Hit Event -> Log into Loss Memory Engine
            sl_hit = (current_price <= sl) if is_buy else (current_price >= sl)
            if sl_hit:
                memory_engine.record_loss(
                    symbol=symbol,
                    action=action,
                    adx=trade.get("adx", 25.0),
                    atr=trade.get("atr", 0.0010)
                )

                msg = (
                    f"🛑 *STOP LOSS HIT: {symbol}*\n"
                    f"Action: *{action}*\n"
                    f"Exit Price: `{current_price}` | SL: `{sl}`\n\n"
                    "🧠 *Memory Engine:* Setup signature recorded.\n"
                    f"🔒 *Lockout:* Banning repeated `{symbol} {action}` setups for 4 hours to protect capital."
                )
                outcome_events.append({"symbol": symbol, "type": "SL", "msg": msg})
                completed_symbols.append(symbol)
                continue

            # 2. Target 3 Hit (Full Win)
            tp3_hit = (current_price >= tp3) if is_buy else (current_price <= tp3)
            if tp3_hit:
                memory_engine.record_win(symbol)
                msg = (
                    f"🎉 *TARGET 3 HIT: {symbol}*\n"
                    f"Action: *{action}*\n"
                    f"Exit Price: `{current_price}` | Final TP: `{tp3}`\n"
                    "Status: *Trade Fully Closed in Profit!*"
                )
                outcome_events.append({"symbol": symbol, "type": "TP3", "msg": msg})
                completed_symbols.append(symbol)
                continue

            # 3. Target 2 Hit
            tp2_hit = (current_price >= tp2) if is_buy else (current_price <= tp2)
            if tp2_hit and not trade["tp2_hit"]:
                trade["tp2_hit"] = True
                msg = f"🎯🎯 *TARGET 2 HIT: {symbol}* @ `{current_price}` (Runner active)"
                outcome_events.append({"symbol": symbol, "type": "TP2", "msg": msg})

            # 4. Target 1 Hit (Breakeven Latch)
            tp1_hit = (current_price >= tp1) if is_buy else (current_price <= tp1)
            if tp1_hit and not trade["tp1_hit"]:
                trade["tp1_hit"] = True
                memory_engine.record_win(symbol)
                trade["sl"] = trade["entry_price"]
                msg = (
                    f"🎯 *TARGET 1 HIT: {symbol}* @ `{current_price}`\n"
                    "🛡️ Stop Loss moved to Entry (Risk-Free Breakeven)."
                )
                outcome_events.append({"symbol": symbol, "type": "TP1", "msg": msg})

        for sym in completed_symbols:
            self.active_trades.pop(sym, None)

        return outcome_events

    @property
    def trades(self):
        return self.active_trades

    @property
    def tracked_trades(self):
        return self.active_trades