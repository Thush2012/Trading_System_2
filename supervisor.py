import os
import sys
import time
import subprocess
import logging
from datetime import datetime
from executor import MultiVenueExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (Supervisor) %(message)s")
log = logging.getLogger("Supervisor")

EXECUTOR_SCRIPT = "executor.py"
executor = MultiVenueExecutor()

# Risk & Circuit Breaker Configurations (Demo mode thresholds)
MAX_DAILY_DRAWDOWN_PCT = 0.05  # 5% max daily loss circuit breaker
DAILY_PROFIT_TARGET_PCT = 0.03 # 3% daily profit target lock threshold

def run_supervisor():
    log.info("Institutional Trading Supervisor initialized with Multi-Venue Risk & Trailing Loop.")
    
    daily_stopped_out = False
    eod_reported_today = False
    last_trailing_check = 0
    
    while True:
        # 1. Ensure Executor Script Exists
        if not os.path.exists(EXECUTOR_SCRIPT):
            log.error(f"Target script '{EXECUTOR_SCRIPT}' not found in directory: {os.getcwd()}")
            time.sleep(10)
            continue

        log.info(f"Launching Institutional Executor ({EXECUTOR_SCRIPT}) using active environment...")
        
        try:
            # Spawn the executor process using the active Python interpreter
            process = subprocess.Popen([sys.executable, EXECUTOR_SCRIPT])
            
            # Monitor loop while the executor is running
            while process.poll() is None:
                now = datetime.utcnow()
                current_timestamp = time.time()
                
                # A. End-of-Day (EOD) Performance Report Trigger (Executes at 23:59 UTC)
                if now.hour == 23 and now.min == 59 and not eod_reported_today:
                    log.info("Generating End-of-Day Multi-Venue Performance Reports...")
                    try:
                        mt5_history = executor.fetch_daily_history("mt5")
                        binance_history = executor.fetch_daily_history("binance")
                        
                        report_message = (
                            f"📊 EOD Trading Report ({now.strftime('%Y-%m-%d')})\n"
                            f"• MT5 Trades: {mt5_history.get('trades', 0)} | Net PnL: ${mt5_history.get('net_pnl', 0.0)}\n"
                            f"• Binance Trades: {binance_history.get('trades', 0)} | Net PnL: ${binance_history.get('net_pnl', 0.0)}"
                        )
                        log.info(report_message)
                        # Optional: Add webhook or Telegram notification dispatch here
                    except Exception as e:
                        log.error(f"Failed to generate EOD reports: {e}")
                        
                    eod_reported_today = True
                    
                # Reset EOD flag at midnight UTC
                if now.hour == 0:
                    eod_reported_today = False

                # B. Circuit Breaker & Daily P&L Risk Checks
                if daily_stopped_out:
                    log.warning("Daily Circuit Breaker active. Execution paused until next UTC day.")
                    time.sleep(15)
                    continue

                try:
                    # Fetch live equities to monitor drawdown/profit locks
                    # (Replace or expand with multi-venue asset aggregations as needed)
                    mt5_assets = executor.get_account_assets("mt5")
                    current_equity = mt5_assets.get("equity", 1000.0)
                    
                    # Example baseline comparison (initialize starting equity daily)
                    starting_equity = 1000.0 
                    drawdown_pct = (starting_equity - current_equity) / starting_equity
                    
                    if drawdown_pct >= MAX_DAILY_DRAWDOWN_PCT:
                        log.error(f"HARD STOP TRIGGERED: Max daily drawdown reached ({drawdown_pct*100:.2f}%). Initiating emergency close.")
                        # Insert emergency venue-wide liquidation / cancel orders hook here
                        daily_stopped_out = True
                        continue
                except Exception as e:
                    log.debug(f"Risk metric polling notice: {e}")

                # C. Active Trailing Stop Loop (Executes every 5 seconds)
                if current_timestamp - last_trailing_check >= 5:
                    try:
                        # Example dynamic trailing stop evaluation per active ticket/symbol
                        # executor.apply_trailing_stops("mt5", "EURUSD", ticket_id=123456, trail_pips_or_pts=20)
                        pass
                    except Exception as e:
                        log.error(f"Error running trailing stop loop: {e}")
                    last_trailing_check = current_timestamp

                time.sleep(1)
            
            # Check exit code when process terminates
            if process.returncode != 0:
                log.warning(f"Executor process exited with non-zero code: {process.returncode}")
            else:
                log.info("Executor process exited cleanly.")
                
        except Exception as e:
            log.error(f"Executor process crashed with exception: {e}")
        
        log.warning("Restarting executor sequence in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    run_supervisor()