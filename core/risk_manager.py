import time
from typing import Dict

class RiskManager:
    def __init__(self, risk_per_trade_pct: float = 0.01, max_daily_drawdown_pct: float = 0.03, cooldown_seconds: int = 14400):
        """
        :param risk_per_trade_pct: Fraction of account to risk per trade (e.g. 0.01 = 1%)
        :param max_daily_drawdown_pct: Hard kill threshold (e.g. 0.03 = 3%)
        :param cooldown_seconds: Asset cooldown duration following consecutive losses (default 4 hours)
        """
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.loss_streak_tracker: Dict[str, int] = {}
        self.cooldown_expiry: Dict[str, float] = {}
        self.cooldown_duration = cooldown_seconds

    def calculate_forex_lot_size(self, balance: float, entry_price: float, sl_price: float, pip_value_standard_lot: float = 10.0) -> float:
        """Calculates MT5 lot size based on pip distance."""
        dollar_risk = balance * self.risk_per_trade_pct
        price_distance = abs(entry_price - sl_price)
        pips_at_risk = price_distance / 0.0001
        if pips_at_risk <= 0:
            return 0.01
        lot_size = dollar_risk / (pips_at_risk * pip_value_standard_lot)
        return max(0.01, round(lot_size, 2))

    def calculate_crypto_position_size(self, balance: float, entry_price: float, sl_price: float) -> float:
        """Calculates coin quantity based on stop distance."""
        dollar_risk = balance * self.risk_per_trade_pct
        risk_per_unit = abs(entry_price - sl_price)
        if risk_per_unit <= 0:
            return 0.0
        quantity = dollar_risk / risk_per_unit
        return round(quantity, 4)

    def record_trade_result(self, symbol: str, is_win: bool):
        """Tracks consecutive losses and applies a time-based cooldown on the asset symbol."""
        now = time.time()
        if is_win:
            self.loss_streak_tracker[symbol] = 0
            if symbol in self.cooldown_expiry:
                del self.cooldown_expiry[symbol]
        else:
            streak = self.loss_streak_tracker.get(symbol, 0) + 1
            self.loss_streak_tracker[symbol] = streak
            if streak >= 2:
                self.cooldown_expiry[symbol] = now + self.cooldown_duration

    def is_symbol_on_cooldown(self, symbol: str) -> tuple[bool, str]:
        """Checks if a symbol is currently locked out due to recent losses."""
        if symbol in self.cooldown_expiry:
            remaining = self.cooldown_expiry[symbol] - time.time()
            if remaining > 0:
                hours_left = remaining / 3600
                return True, f"Symbol on loss cooldown ({hours_left:.1f}h remaining)"
            else:
                del self.cooldown_expiry[symbol]
                self.loss_streak_tracker[symbol] = 0
        return False, "OK"