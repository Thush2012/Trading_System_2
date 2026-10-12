import os
import asyncio
import logging
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
from core.config import Config
from core.logger import setup_system_logger
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

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase client initialized successfully.")
    except Exception as e:
        log.error(f"Failed to connect to Supabase: {e}")

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

async def handle_ping(request):
    return web.Response(text="Dual Market Trade Engine is Running 24/7!")

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

def push_signal_to_supabase(signal: dict):
    if not supabase:
        log.warning("Supabase client not active. Skipping DB push.")
        return
    try:
        data = {
            "symbol": signal["symbol"],
            "action": signal["action"],
            "entry_price": float(signal["current_price"]),
            "sl": float(signal["sl"]),
            "tp": float(signal["tp"]),
            "sl_pips": float(signal["sl_pips"]),
            "tp_pips": float(signal["tp_pips"]),
            "status": "PENDING"
        }
        supabase.table("trade_signals").insert(data).execute()
        log.info(f"Pushed {signal['symbol']} {signal['action']} to Supabase queue.")
    except Exception as e:
        log.error(f"Supabase push error: {e}")

async def scheduled_scan_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        log.info("Running automated 15-minute background Forex market scan...")
        report = await global_scanner.scan_all(bypass_cooldown=False)
        if not report.empty:
            for _, row in report.iterrows():
                signal_dict = row.to_dict()
                msg = format_signal_message(signal_dict)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                # Enqueue into Supabase for local executor
                push_signal_to_supabase(signal_dict)
    except Exception as e:
        log.error(f"Background evaluation error: {e}")

async def post_init_hook(application):
    await start_web_server()
    startup_text = (
        "💎 *Forex Trade Engine Online*\n\n"
        "• Deployment: Active 24/7 Cloud (Render)\n"
        "• Queue: Supabase Active\n"
        "• Model: Single Take Profit (1.5 ATR)\n"
        "• Auto Scan: Active (15m Intervals)"
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
            interval=900,
            first=30
        )
        log.info("15-minute background scan loop scheduled.")

    log.info("Master Engine polling for updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()