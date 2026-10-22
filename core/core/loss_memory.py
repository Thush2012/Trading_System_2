import os
import json
from datetime import datetime, timezone
from core.logger import setup_system_logger

log = setup_system_logger("LossMemory")
MEMORY_PATH = "loss_memory.json"

class LossMemoryEngine:
    def __init__(self, ban_seconds: int = 10800):
        self.ban_seconds = ban_seconds  # 3-hour lockout per failed direction
        self.state = self._read_disk()

    def _read_disk(self) -> dict:
        if os.path.exists(MEMORY_PATH):
            try:
                with open(MEMORY_PATH, "r") as f:
                    return json.load(f)
            except Exception as err:
                log.error(f"Could not read memory file: {err}")
        return {
            "locked_directions": {},
            "in_recovery": False,
            "deficit_usd": 0.0,
            "loss_streak": 0
        }

    def _write_disk(self):
        try:
            with open(MEMORY_PATH, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as err:
            log.error(f"Could not save memory file: {err}")

    def register_stop_loss(self, symbol: str, direction: str, loss_usd: float, adx_at_entry: float):
        now_ts = datetime.now(timezone.utc).timestamp()
        pattern_id = f"{symbol}_{direction.upper()}"

        self.state["locked_directions"][pattern_id] = {
            "expires": now_ts + self.ban_seconds,
            "failed_adx": adx_at_entry
        }
        self.state["in_recovery"] = True
        self.state["deficit_usd"] = round(self.state.get("deficit_usd", 0.0) + abs(loss_usd), 2)
        self.state["loss_streak"] = self.state.get("loss_streak", 0) + 1
        self._write_disk()
        log.warning(f"Memory Lock Engaged: {pattern_id} banned for 3h. Recovery Deficit: ${self.state['deficit_usd']}")

    def register_take_profit(self, profit_usd: float):
        if self.state.get("in_recovery", False):
            remaining = self.state.get("deficit_usd", 0.0) - abs(profit_usd)
            if remaining <= 0.10:
                self.state["in_recovery"] = False
                self.state["deficit_usd"] = 0.0
                self.state["loss_streak"] = 0
                log.info("Deficit recovered. Returning to standard parameters.")
            else:
                self.state["deficit_usd"] = round(remaining, 2)
        else:
            self.state["loss_streak"] = 0
        self._write_disk()

    def check_permission(self, symbol: str, direction: str, current_adx: float) -> tuple[bool, str, dict]:
        now_ts = datetime.now(timezone.utc).timestamp()
        pattern_id = f"{symbol}_{direction.upper()}"

        # Clean up expired bans
        expired_keys = [
            k for k, v in self.state["locked_directions"].items()
            if now_ts >= v.get("expires", 0)
        ]
        for k in expired_keys:
            del self.state["locked_directions"][k]
        if expired_keys:
            self._write_disk()

        # Check active directional ban
        if pattern_id in self.state["locked_directions"]:
            entry = self.state["locked_directions"][pattern_id]
            mins_left = int((entry["expires"] - now_ts) / 60)
            return False, f"Blocked by Loss Memory ({mins_left}m left)", {}

        # Daily circuit breaker on 3 consecutive losses
        if self.state.get("loss_streak", 0) >= 3:
            return False, "Circuit Breaker: 3 consecutive losses reached", {}

        meta = {
            "recovery_active": self.state.get("in_recovery", False),
            "deficit_usd": self.state.get("deficit_usd", 0.0)
        }
        return True, "Allowed", meta