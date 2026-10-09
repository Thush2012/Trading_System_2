import os
import asyncio
import logging
from aiohttp import web
from telegram import Update
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

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

async def handle_ping(request):
    """Health check endpoint to keep cloud nodes (Render/VPS) active."""
    return web.Response(text="Dual Market Trade Engine is Running 24/7!")

async def start_web_server():
    """Runs a lightweight HTTP server bound to the hosting port."""
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health check web server running on port {port}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Logs unexpected exceptions from polling or tasks."""
    log.error(f"Telegram error encountered: {context.error}")

async def scheduled_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Background cycle: checks active trade targets and scans for new setups."""
    try:
        # 1. Evaluate open trades against live prices for TP/SL hits
        log.info("Checking active trades against live price targets...")
        trade_updates = tracker.evaluate_active_trades()
        for update_event in trade_updates:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=update_event["msg"],
                parse_mode="Markdown"
            )
            log.info(f"Published outcome update for {update_event['symbol']}: {update_event['type']}")

        # 2. Run automated 15-minute market scanner
        log.info("Running automated 15-minute background market scan...")
        report = await global_scanner.scan_all(bypass_cooldown=False)
        if not report.empty:
            for _, row in report.iterrows():
                msg = format_signal_message(row)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                # Register new setup in active outcome tracker
                ticker = global_scanner.market_map.get(row["symbol"].replace("USDT", "USD"), {}).get("ticker", "")
                if ticker:
                    tracker.register_trade(row.to_dict(), ticker)
                log.info(f"Signal for {row['symbol']} delivered and registered in tracker.")

    except Exception as e:
        log.error(f"Background evaluation error: {e}")

async def post_init_hook(application):
    """Initializes the background web server and sends a boot confirmation."""
    await start_web_server()

    startup_text = (
        "💎 **Dual Market Trade Engine Online**\n\n"
        "• Deployment: Active 24/7 Cloud/Local Mode\n"
        "• Auto Scan & TP/SL Tracker: Active (15m Intervals)\n"
        "• Outcome Alerts: Automatic TP1, TP2, TP3 & SL Tracking\n"
        "• Commands: Listening for user interactions"
    )
    try:
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=startup_text,
            parse_mode="Markdown"
        )
    except Exception as ex:
        log.error(f"Could not send boot alert: {ex}")

def main():
    log.info("==================================================")
    log.info("        DUAL MARKET TRADE ENGINE (CLOUD READY)    ")
    log.info("==================================================")

    # Build Application
    app = (
        ApplicationBuilder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init_hook)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("hours", cmd_trading_hours))
    app.add_handler(CommandHandler("rules", cmd_risk_rules))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_press))
    app.add_error_handler(error_handler)

    # Schedule 15-minute background scans using built-in JobQueue
    if app.job_queue:
        app.job_queue.run_repeating(
            scheduled_scan_job,
            interval=900,  # 15 minutes
            first=30       # Starts checking 30 seconds after boot
        )
        log.info("15-minute background scan & tracker loop scheduled.")

    log.info("Master Engine polling for updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()