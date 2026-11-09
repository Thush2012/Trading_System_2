import asyncio
import time
import traceback

import schedule

from core.logger import setup_system_logger
from core.notifier import TelegramNotifier
from run_live_engine import run_trading_cycle
from core.config import Config
TELEGRAM_BOT_TOKEN = Config.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = Config.TELEGRAM_CHAT_ID
log = setup_system_logger("Daemon")
notifier = TelegramNotifier(bot_token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)

def execute_safe_cycle():
    """Runs a single trading cycle inside a resilient boundary."""
    log.info("Starting scheduled hourly execution cycle...")
    try:
        asyncio.run(run_trading_cycle())
        log.info("Scheduled cycle completed cleanly.")
    except Exception as e:
        error_details = traceback.format_exc()
        log.error(f"Critical execution fault: {e}\n{error_details}")
        
        # Send error alert to Telegram so you are notified of issues immediately
        fail_msg = f"⚠️ *Trading Engine Alert*\nError during cycle: `{e!s}`\nCheck `trading_system.log` for details."
        notifier.send_alert(fail_msg)

# Schedule execution at the top of every hour (:00)
schedule.every().hour.at(":00").do(execute_safe_cycle)

if __name__ == "__main__":
    log.info("System daemon booted. Initializing first cycle immediately...")
    execute_safe_cycle()

    log.info("Continuous daemon running. Waiting for hourly triggers (Press Ctrl+C to exit)...")
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            log.warning("User issued interrupt signal. Shutting down daemon.")
            break
        except Exception as loop_err:
            log.critical(f"Unexpected loop exception: {loop_err}")
            time.sleep(5)