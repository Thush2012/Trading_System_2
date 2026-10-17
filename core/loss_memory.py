import os
import json
from datetime import datetime, timezone
from supabase import create_client, Client
from core.logger import setup_system_logger

log = setup_system_logger("AdaptiveBrain")
MEMORY_PATH = "loss_memory.json"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class LossMemoryEngine:
    def __init__(self, ban_seconds: int = 10800):
        self.ban_seconds = ban_seconds
        self.supabase: Client | None = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            except Exception as e:
                log.error(f"Supabase brain connection failed: {e}")

        self.state = self._read_disk()
        self._sync_from_cloud()

    def _read_disk(self) -> dict:
        if os.path.exists(MEMORY_PATH):
            try:
                with open(MEMORY_PATH, "r") as f:
                    data = json.load(f)
                    if "learned_rules" not in data:
                        data["learned_rules"] = {}
                    return data
            except Exception as err:
                log.error(f"Could not read memory file: {err}")
        return {
            "locked_directions": {},
            "in_recovery": False,
            "deficit_usd": 0.0,
            "loss_streak": 0,
            "learned_rules": {}  # Permanent day-by-day learned rules per pair
        }

    def _write_disk(self):
        try:
            with open(MEMORY_PATH, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as err:
            log.error(f"Could not save memory file: {err}")

    def _sync_from_cloud(self):
        """Loads permanent learned parameters from Supabase on startup."""
        if not self.supabase:
            return
        try:
            res = self.supabase.table("bot_learning_memory").select("*").execute()
            for row in res.data:
                sym = row["symbol"]
                self.state["learned_rules"][sym] = {
                    "min_adx": float(row["learned_min_adx"]),
                    "pullback_atr": float(row["learned_pullback_atr"]),
                    "wins": int(row["total_wins"]),
                    "losses": int(row["total_losses"]),
                    "hour_losses": row.get("banned_utc_hours", {})
                }
            self._write_disk()
            log.info("Synced permanent self-learning rules from Supabase.")
        except Exception as e:
            log.warning(f"Cloud brain sync skipped: {e}")

    def _push_rule_to_cloud(self, symbol: str, rule: dict):
        if not self.supabase:
            return
        try:
            payload = {
                "symbol": symbol,
                "learned_min_adx": rule["min_adx"],
                "learned_pullback_atr": rule["pullback_atr"],
                "total_wins": rule["wins"],
                "total_losses": rule["losses"],
                "banned_utc_hours": rule["hour_losses"],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            self.supabase.table("bot_learning_memory").upsert(payload).execute()
        except Exception as e:
            log.error(f"Failed to push learned rule for {symbol} to cloud: {e}")

    def get_pair_rules(self, symbol: str) -> dict:
        """Returns the current evolved thresholds for a specific pair."""
        if symbol not in self.state["learned_rules"]:
            self.state["learned_rules"][symbol] = {
                "min_adx": 25.0,
                "pullback_atr": 0.55,
                "wins": 0,
                "losses": 0,
                "hour_losses": {}
            }
        return self.state["learned_rules"][symbol]

    def register_stop_loss(self, symbol: str, direction: str, loss_usd: float, adx_at_entry: float):
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        current_hour = str(now.hour)
        pattern_id = f"{symbol}_{direction.upper()}"

        # 1. Short-term 3-hour directional lockout
        self.state["locked_directions"][pattern_id] = {
            "expires": now_ts + self.ban_seconds,
            "failed_adx": adx_at_entry
        }
        self.state["in_recovery"] = True
        self.state["deficit_usd"] = round(self.state.get("deficit_usd", 0.0) + abs(loss_usd), 2)
        self.state["loss_streak"] = self.state.get("loss_streak", 0) + 1

        # 2. Long-Term Day-by-Day Learning Evolution
        rule = self.get_pair_rules(symbol)
        rule["losses"] += 1

        # If it lost at an ADX near our threshold, permanently tighten the ADX requirement (cap at 32.0)
        if adx_at_entry <= rule["min_adx"] + 2.5:
            rule["min_adx"] = round(min(32.0, max(rule["min_adx"] + 1.0, adx_at_entry + 1.0)), 1)

        # Tighten the EMA pullback requirement so it stops chasing extended candles (floor at 0.35 ATR)
        rule["pullback_atr"] = round(max(0.35, rule["pullback_atr"] - 0.03), 2)

        # Track which UTC hour the loss occurred in
        hour_map = rule.get("hour_losses", {})
        if not isinstance(hour_map, dict):
            hour_map = {}
        hour_map[current_hour] = hour_map.get(current_hour, 0) + 1
        rule["hour_losses"] = hour_map

        self._write_disk()
        self._push_rule_to_cloud(symbol, rule)

        log.warning(
            f"Brain Evolved on {symbol} Loss | New Min ADX: {rule['min_adx']} | "
            f"New Pullback Limit: {rule['pullback_atr']}x ATR | Hour {current_hour} UTC Losses: {hour_map[current_hour]}"
        )

    def register_take_profit(self, symbol: str, profit_usd: float):
        if self.state.get("in_recovery", False):
            remaining = self.state.get("deficit_usd", 0.0) - abs(profit_usd)
            if remaining <= 0.10:
                self.state["in_recovery"] = False
                self.state["deficit_usd"] = 0.0
                self.state["loss_streak"] = 0
            else:
                self.state["deficit_usd"] = round(remaining, 2)
        else:
            self.state["loss_streak"] = 0

        # Reinforce winning behavior: slightly relax overly tight ADX if pair is on a hot streak
        rule = self.get_pair_rules(symbol)
        rule["wins"] += 1
        if rule["wins"] > rule["losses"] and rule["min_adx"] > 25.0:
            rule["min_adx"] = round(max(25.0, rule["min_adx"] - 0.2), 1)

        self._write_disk()
        self._push_rule_to_cloud(symbol, rule)

    def check_permission(self, symbol: str, direction: str, current_adx: float) -> tuple[bool, str, dict]:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        current_hour = str(now.hour)
        pattern_id = f"{symbol}_{direction.upper()}"

        # Clean expired 3h lockouts
        expired = [k for k, v in self.state["locked_directions"].items() if now_ts >= v.get("expires", 0)]
        for k in expired:
            del self.state["locked_directions"][k]

        if pattern_id in self.state["locked_directions"]:
            entry = self.state["locked_directions"][pattern_id]
            mins_left = int((entry["expires"] - now_ts) / 60)
            return False, f"Blocked by 3h Loss Lockout ({mins_left}m left)", {}

        if self.state.get("loss_streak", 0) >= 3:
            return False, "Circuit Breaker: 3 consecutive losses reached", {}

        # Check Permanent Learned Rules for this Pair
        rule = self.get_pair_rules(symbol)
        hour_losses = rule.get("hour_losses", {})
        if isinstance(hour_losses, dict) and hour_losses.get(current_hour, 0) >= 2:
            return False, f"Learned Hour Blacklist: {symbol} has lost {hour_losses[current_hour]}x at Hour {current_hour}:00 UTC", {}

        if current_adx < rule["min_adx"]:
            return False, f"Below Learned ADX ({current_adx:.1f} < {rule['min_adx']})", {}

        meta = {
            "recovery_active": self.state.get("in_recovery", False),
            "deficit_usd": self.state.get("deficit_usd", 0.0),
            "learned_min_adx": rule["min_adx"],
            "learned_pullback_atr": rule["pullback_atr"]
        }
        return True, "Allowed", meta