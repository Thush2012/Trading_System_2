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

MAX_CONCURRENT_OPEN_TRADES = 1

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

def get_active_trades_count(tr: TradeTracker) -> int:
    """Safely inspects active trade count across different tracker structures."""
    for attr in ("active_trades", "trades", "tracked_trades", "open_trades"):
        val = getattr(tr, attr, None)
        if isinstance(val, dict):
            return len(val)
        if isinstance(val, list):
            return len(val)
    return 0

async def handle_ping(request):
    feed_status = "Live MT5 Connected" if getattr(global_scanner, "mt5_initialized", False) else "Web Fallback Active"
    return web.Response(text=f"Dual Market Trade Engine is Running 24/7! ({feed_status})")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health check web server running on port {port}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Telegram error encountered: {context.error}")

async def scheduled_scan_job(context: ContextTypes.DEFAULT_TYPE):
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

        # 2. Portfolio Exposure Check: Block new signals if trade is already open
        active_count = get_active_trades_count(tracker)
        if active_count >= MAX_CONCURRENT_OPEN_TRADES:
            log.info(f"Active trade limit reached ({active_count}/{MAX_CONCURRENT_OPEN_TRADES}). Skipping scan to protect capital.")
            return

        # 3. Run automated 15-minute background market scan
        log.info("Running automated 15-minute background market scan...")
        report = await global_scanner.scan_all(bypass_cooldown=False, enforce_window=True)
        if not report.empty:
            for _, row in report.iterrows():
                # Re-check open trade limit before firing
                if get_active_trades_count(tracker) >= MAX_CONCURRENT_OPEN_TRADES:
                    break
                signal_dict = row.to_dict()
                msg = format_signal_message(signal_dict)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                ticker = global_scanner.market_map.get(row["symbol"], {}).get("ticker", "")
                if ticker:
                    tracker.register_trade(signal_dict, ticker)
                log.info(f"Signal for {row['symbol']} delivered and registered in tracker.")

    except Exception as e:
        log.error(f"Background evaluation error: {e}")

async def post_init_hook(application):
    await start_web_server()

    feed_mode = "Direct MT5 Live Feed" if getattr(global_scanner, "mt5_initialized", False) else "Cloud Standalone Mode"
    startup_text = (
        "💎 **Dual Market Trade Engine Online**\n\n"
        f"• Status: {feed_mode}\n"
        "• Focus: 100% Forex Major & Cross Pairs\n"
        "• Active Window: 1:30 PM – 9:30 PM SLT\n"
        "• Risk Rule: Maximum 1 Active Trade\n"
        "• Auto Scan & TP/SL Tracker: Active (15m Intervals)\n"
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
    log.info("        DUAL MARKET TRADE ENGINE (PRO STABLE)     ")
    log.info("==================================================")

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
            first=30
        )
        log.info("15-minute background scan & tracker loop scheduled.")

    log.info("Master Engine polling for updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()