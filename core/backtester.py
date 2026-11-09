import pandas as pd

from core.strategy import StrategyEngine


class Backtester:
    def __init__(self, initial_balance: float = 10000.0, risk_per_trade: float = 0.01):
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.strategy = StrategyEngine()

    def run(self, df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
        if df is None or df.empty or len(df) < 30:
            return {
                "final_balance": self.initial_balance,
                "total_return_pct": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0
            }, pd.DataFrame()

        signals_df = self.strategy.generate_signals(df)

        balance = self.initial_balance
        trades = []
        in_trade = False
        trade_side = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0

        for i in range(len(signals_df)):
            row = signals_df.iloc[i]
            action = row.get("action", "")
            curr_price = row.get("close", 0.0)
            time = row.name if not isinstance(row.name, int) else f"Step {i}"

            if in_trade:
                won = False
                closed = False
                pnl = 0.0

                if trade_side == "BUY":
                    if curr_price >= tp_price:
                        won = True
                        closed = True
                        pnl = balance * (self.risk_per_trade * 2.0)
                    elif curr_price <= sl_price:
                        won = False
                        closed = True
                        pnl = - (balance * self.risk_per_trade)
                elif trade_side == "SELL":
                    if curr_price <= tp_price:
                        won = True
                        closed = True
                        pnl = balance * (self.risk_per_trade * 2.0)
                    elif curr_price >= sl_price:
                        won = False
                        closed = True
                        pnl = - (balance * self.risk_per_trade)

                if closed:
                    balance += pnl
                    trades.append({
                        "exit_time": time,
                        "side": trade_side,
                        "entry": entry_price,
                        "exit": curr_price,
                        "pnl": round(pnl, 2),
                        "balance": round(balance, 2),
                        "outcome": "WIN" if won else "LOSS"
                    })
                    in_trade = False
                    trade_side = None

            if not in_trade and action in ["🟢 BUY", "🔴 SELL"]:
                in_trade = True
                trade_side = "BUY" if "BUY" in action else "SELL"
                entry_price = row.get("entry_price", curr_price)
                sl_price = row.get("stop_loss", curr_price * 0.99)
                tp_price = row.get("take_profit", curr_price * 1.02)

        trades_df = pd.DataFrame(trades)

        if not trades_df.empty:
            wins = trades_df[trades_df["outcome"] == "WIN"]
            losses = trades_df[trades_df["outcome"] == "LOSS"]
            win_rate = (len(wins) / len(trades_df)) * 100
            gross_win = wins["pnl"].sum()
            gross_loss = abs(losses["pnl"].sum())
            profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
            total_return = ((balance - self.initial_balance) / self.initial_balance) * 100
        else:
            win_rate = 0.0
            profit_factor = 0.0
            total_return = 0.0

        summary = {
            "final_balance": round(balance, 2),
            "total_return_pct": round(total_return, 2),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": profit_factor
        }

        return summary, trades_df
    # At the bottom of core/backtester.py:
BacktestEngine = Backtester