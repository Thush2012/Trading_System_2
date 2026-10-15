import os
import json
import logging
from datetime import datetime, timezone
from core.logger import setup_system_logger

log = setup_system_logger("LossMemory")
MEMORY_FILE = "loss_memory.json"

class LossMemoryEngine:
    def __init__(self, lock_duration_sec: int = 14400):  # 4-hour directional lockout
        self.lock_duration_sec = lock_duration_sec
        self.memory = self._load_memory()

    def _load_memory(self) -> dict:
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Error loading loss memory: {e}")
        return {"banned_patterns": {}, "pair_stats": {}}

    def _save_memory(self):
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            log.error(f"Error saving loss memory: {e}")

    def record_loss(self, symbol: str, action: str, adx: float, atr: float):
        """Records a failed trade signature to prevent repeating it."""
        now = datetime.now(timezone.utc).timestamp()
        key = f"{symbol}_{action.upper()}"

        # 1. Ban this exact direction and pair for the lockout duration
        self.memory["banned_patterns"][key] = {
            "symbol": symbol,
            "action": action.upper(),
            "failed_at": now,
            "adx_at_failure": adx,
            "atr_at_failure": atr,
            "expires_at": now + self.lock_duration_sec
        }

        # 2. Track consecutive failures per pair for circuit breaking
        stats = self.memory["pair_stats"].get(symbol, {"consecutive_losses": 0, "last_loss": 0})
        stats["consecutive_losses"] += 1
        stats["last_loss"] = now
        self.memory["pair_stats"][symbol] = stats

        self._save_memory()
        log.warning(f"🧠 Memory Recorded: Banned {key} until {datetime.fromtimestamp(now + self.lock_duration_sec, tz=timezone.utc).strftime('%H:%M UTC')}")

    def record_win(self, symbol: str):
        """Resets loss penalty counters on winning trades."""
        if symbol in self.memory["pair_stats"]:
            self.memory["pair_stats"][symbol]["consecutive_losses"] = 0
            self._save_memory()

    def is_setup_allowed(self, symbol: str, action: str, current_adx: float) -> tuple[bool, str]:
        """Checks incoming setups against memory of previous failures."""
        now = datetime.now(timezone.utc).timestamp()
        key = f"{symbol}_{action.upper()}"

        # Check Active Directional Lockout
        if key in self.memory["banned_patterns"]:
            ban = self.memory["banned_patterns"][key]
            if now < ban["expires_at"]:
                remaining_mins = int((ban["expires_at"] - now) / 60)
                if current_adx < (ban["adx_at_failure"] + 4.0):
                    return False, f"Memory Lockout: {key} failed recently. Blocked for {remaining_mins}m (Needs ADX >= {ban['adx_at_failure'] + 4.0:.1f})"
            else:
                del self.memory["banned_patterns"][key]
                self._save_memory()

        # Check Daily Circuit Breaker (2 consecutive losses on same pair)
        stats = self.memory["pair_stats"].get(symbol, {})
        if stats.get("consecutive_losses", 0) >= 2:
            if now - stats.get("last_loss", 0) < 43200:  # 12-hour cool-off
                return False, f"Circuit Breaker: {symbol} has 2 consecutive losses. Cooldown active."
            else:
                stats["consecutive_losses"] = 0
                self._save_memory()

        return True, "OK"