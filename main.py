import os
import logging
from datetime import datetime
import pytz
from aiohttp import web
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from core.config import Config
from core.logger import setup_system_logger
from core.tracker import TradeTracker
from telegram_bot import (
    cmd_start,
    cmd_scan,
    cmd_status,
    cmd_trading_hours,
    cmd_risk_rules,
    handle_button_press,
    format_signal_message,
    global_scanner
)

log = setup_system_logger("MasterEngine")
ADMIN_CHAT_ID = Config.TELEGRAM_CHAT_ID
tracker = TradeTracker()

MAX_CONCURRENT_OPEN_TRADES = 2
SLT_TZ = pytz.timezone("Asia/Colombo")

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

def get_open_trade_count(tr: TradeTracker) -> int:
    for attr in ("active_trades", "trades", "tracked_trades"):
        val = getattr(tr, attr, None)
        if isinstance(val, (dict, list)):
            return len(val)
    return 0

async def handle_ping(request):
    now_slt = datetime.now(SLT_TZ)
    is_weekend = now_slt.weekday() >= 5
    window_status = "Weekend Standby" if is_weekend else "24/7 Manual Alert Mode Active"
    return web.Response(text=f"Manual Trading Engine Running 24/7 | Mode: {window_status}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health check server active on port {port}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Telegram error: {context.error}")

async def scheduled_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """24/7 Background Loop: Evaluates active trades, updates loss memory, and alerts Telegram."""
    try:
        # 1. Evaluate open trades against live prices (Updates Loss Memory & Recovery state)
        trade_updates = tracker.evaluate_active_trades()
        for event in trade_updates:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=event["msg"],
                parse_mode="Markdown"
            )
            log.info(f"Trade outcome recorded for {event['symbol']}: {event['type']}")

        # 2. Enforce portfolio exposure limit
        if get_open_trade_count(tracker) >= MAX_CONCURRENT_OPEN_TRADES:
            log.info("Max concurrent trades active. Skipping new signal dispatch.")
            return

        # 3. Run market scan (enforce_window=True ensures alerts fire Mon-Fri during trading windows)
        report = await global_scanner.scan_all(bypass_cooldown=False, enforce_window=True)
        if not report.empty:
            for _, row in report.iterrows():
                if get_open_trade_count(tracker) >= MAX_CONCURRENT_OPEN_TRADES:
                    break

                sig_dict = row.to_dict()
                msg = format_signal_message(sig_dict)

                # Send manual execution alert to Telegram
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )

                # Register trade in tracker so it monitors SL/TP milestones and feeds Loss Memory
                ticker = global_scanner.market_map.get(sig_dict["symbol"], {}).get("ticker", "")
                if ticker:
                    tracker.register_trade(sig_dict, ticker)
                log.info(f"Manual signal dispatched for {sig_dict['symbol']}.")

    except Exception as err:
        log.error(f"Background loop error: {err}")

async def post_init_hook(application):
    await start_web_server()
    now_slt = datetime.now(SLT_TZ).strftime("%Y-%m-%d %I:%M %p SLT")
    startup_msg = (
        "💎 *Manual Trading & Memory Engine Online*\n\n"
        f"• *Boot Time:* `{now_slt}`\n"
        "• *Execution Mode:* 100% Manual Input (Alerts to Telegram)\n"
        "• *Loss Memory:* Active (Tracks outcomes & evolves pair rules)\n"
        "• *Target Model:* Asymmetric 1.6R / 2.0R Recovery Payoff"
    )
    try:
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=startup_msg,
            parse_mode="Markdown"
        )
    except Exception as exc:
        log.error(f"Startup notification failed: {exc}")

def main():
    log.info("Initializing Manual Trading Engine...")
    app = (
        ApplicationBuilder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init_hook)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("hours", cmd_trading_hours))
    app.add_handler(CommandHandler("rules", cmd_risk_rules))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_press))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_repeating(
            scheduled_scan_job,
            interval=900,  # 15 minutes
            first=20
        )
        log.info("Background scan schedule registered.")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()