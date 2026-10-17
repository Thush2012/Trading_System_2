import yfinance as yf
from datetime import datetime, timezone
from core.logger import setup_system_logger
from core.loss_memory import LossMemoryEngine

log = setup_system_logger("TradeTracker")
memory_guard = LossMemoryEngine()

class TradeTracker:
    def __init__(self):
        self.active_trades = {}

    def register_trade(self, sig: dict, ticker: str):
        sym = sig["symbol"]
        self.active_trades[sym] = {
            "symbol": sym,
            "action": sig["action"],
            "entry_price": float(sig["current_price"]),
            "sl": float(sig["sl"]),
            "tp": float(sig.get("tp", sig.get("tp1", 0.0))),
            "sl_pips": float(sig.get("sl_pips", 15.0)),
            "tp_pips": float(sig.get("tp_pips", 20.0)),
            "adx": float(sig.get("adx", 25.0)),
            "ticker": ticker
        }

    def _fetch_price(self, ticker: str) -> float | None:
        try:
            df = yf.download(ticker, period="1d", interval="1m", progress=False)
            if not df.empty:
                if isinstance(df.columns, object) and hasattr(df.columns, "get_level_values"):
                    df.columns = df.columns.get_level_values(0)
                return float(df["Close"].iloc[-1])
        except Exception as err:
            log.error(f"Tracker quote error ({ticker}): {err}")
        return None

    def evaluate_active_trades(self) -> list:
        events = []
        closed = []

        for sym, tr in list(self.active_trades.items()):
            px = self._fetch_price(tr["ticker"])
            if px is None:
                continue

            is_buy = "BUY" in tr["action"]
            sl_hit = (px <= tr["sl"]) if is_buy else (px >= tr["sl"])
            tp_hit = (px >= tr["tp"]) if is_buy else (px <= tr["tp"])

            if sl_hit:
                est_loss = round(tr["sl_pips"] * 0.10, 2)
                memory_guard.register_stop_loss(sym, tr["action"], est_loss, tr["adx"])
                msg = (
                    f"🛑 *STOP LOSS HIT: {sym}*\n"
                    f"Direction: *{tr['action']}* | Exit: `{px}`\n"
                    "🧠 *Memory Engine:* Deficit recorded & rules evolved. Direction locked for 3h."
                )
                events.append({"symbol": sym, "type": "SL", "msg": msg})
                closed.append(sym)

            elif tp_hit:
                est_win = round(tr["tp_pips"] * 0.10, 2)
                memory_guard.register_take_profit(sym, est_win)
                msg = (
                    f"🎯 *TAKE PROFIT HIT: {sym}*\n"
                    f"Direction: *{tr['action']}* | Exit: `{px}`\n"
                    "✅ *Memory Engine:* Profit recorded, deficit reduced, rules reinforced."
                )
                events.append({"symbol": sym, "type": "TP", "msg": msg})
                closed.append(sym)

        for s in closed:
            self.active_trades.pop(s, None)

        return events