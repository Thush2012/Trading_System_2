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

MAX_CONCURRENT_OPEN_TRADES = 2

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

def get_active_trades_count(tr: TradeTracker) -> int:
    for attr in ("active_trades", "trades", "tracked_trades", "open_trades"):
        val = getattr(tr, attr, None)
        if isinstance(val, (dict, list)):
            return len(val)
    return 0

async def handle_ping(request):
    feed = "Live MT5" if getattr(global_scanner, "mt5_initialized", False) else "Web Engine"
    return web.Response(text=f"Multi-Timeframe Engine Online (Feed: {feed})")

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
    log.error(f"Telegram handler error: {context.error}")

async def scheduled_scan_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        # 1. Evaluate open trades for TP/SL hits
        trade_updates = tracker.evaluate_active_trades()
        for update_event in trade_updates:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=update_event["msg"],
                parse_mode="Markdown"
            )

        # 2. Maximum open position limit
        if get_active_trades_count(tracker) >= MAX_CONCURRENT_OPEN_TRADES:
            return

        # 3. Multi-timeframe scan cycle
        report = await global_scanner.scan_all(bypass_cooldown=False, enforce_window=True)
        if not report.empty:
            for _, row in report.iterrows():
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
                log.info(f"Dispatched {row['symbol']} [{row.get('timeframe')}] signal to Telegram.")

    except Exception as e:
        log.error(f"Scheduled scan job error: {e}")

async def post_init_hook(application):
    await start_web_server()
    feed_mode = "Direct MT5 Feed" if getattr(global_scanner, "mt5_initialized", False) else "Cloud Standalone"
    startup_text = (
        "💎 *Multi-Timeframe Forex Engine Online*\n\n"
        f"• Status: {feed_mode}\n"
        "• Horizons: 5m (Scalp), 15m (Intraday), 1h (Macro Trend)\n"
        "• Schedule: 5-minute automated checks (24/5)\n"
        "• Target Model: Multi-tier TP1, TP2, TP3 with Breakeven Latch"
    )
    try:
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=startup_text,
            parse_mode="Markdown"
        )
    except Exception as ex:
        log.error(f"Boot notification failure: {ex}")

def main():
    log.info("Starting Multi-Timeframe Forex Trade Engine...")
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
        # Run background scanner every 5 minutes (300 seconds)
        app.job_queue.run_repeating(
            scheduled_scan_job,
            interval=300,
            first=20
        )
        log.info("5-minute multi-timeframe background job queue initialized.")

    log.info("Polling Telegram updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()