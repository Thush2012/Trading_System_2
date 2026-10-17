import os
import logging
from datetime import datetime
import pytz
from aiohttp import web
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
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

# Initialize Supabase Client for Auto-Execution Queue
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client | None = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase signal queue connected.")
    except Exception as err:
        log.error(f"Supabase initialization error: {err}")

logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

def get_open_trade_count(tr: TradeTracker) -> int:
    for attr in ("active_trades", "trades", "tracked_trades"):
        val = getattr(tr, attr, None)
        if isinstance(val, (dict, list)):
            return len(val)
    return 0

def push_to_supabase(sig: dict):
    """Enqueues validated trade signals to Supabase during active weekday trading hours."""
    if not supabase:
        return
    try:
        payload = {
            "symbol": sig["symbol"],
            "action": sig["action"],
            "entry_price": float(sig["current_price"]),
            "sl": float(sig["sl"]),
            "tp": float(sig.get("tp", sig.get("tp1", 0.0))),
            "sl_pips": float(sig.get("sl_pips", 0.0)),
            "tp_pips": float(sig.get("tp_pips", 0.0)),
            "status": "PENDING"
        }
        supabase.table("trade_signals").insert(payload).execute()
        log.info(f"Queued {sig['symbol']} {sig['action']} into Supabase for MT5 execution.")
    except Exception as exc:
        log.error(f"Supabase insert error: {exc}")

async def handle_ping(request):
    now_slt = datetime.now(SLT_TZ)
    is_weekend = now_slt.weekday() >= 5
    window_status = "Weekend Standby" if is_weekend else (
        "Active Trading Window" if global_scanner.is_within_trading_window() else "24/7 Analysis Mode"
    )
    return web.Response(text=f"Forex Engine Running 24/7 | Mode: {window_status}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health check server listening on port {port}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Telegram error: {context.error}")

async def scheduled_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """24/7 Background Loop: Evaluates active trades, updates loss memory, and scans markets."""
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

        # 3. Run 24/7 market analysis (enforce_window=True ensures signals only fire Mon-Fri 1:30-9:30 PM SLT)
        report = await global_scanner.scan_all(bypass_cooldown=False, enforce_window=True)
        if not report.empty:
            for _, row in report.iterrows():
                if get_open_trade_count(tracker) >= MAX_CONCURRENT_OPEN_TRADES:
                    break

                sig_dict = row.to_dict()
                msg = format_signal_message(sig_dict)

                # Send alert to Telegram
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )

                # Push to Supabase for local MT5 auto-execution
                push_to_supabase(sig_dict)

                # Register trade in tracker for SL/TP memory monitoring
                ticker = global_scanner.market_map.get(sig_dict["symbol"], {}).get("ticker", "")
                if ticker:
                    tracker.register_trade(sig_dict, ticker)

    except Exception as err:
        log.error(f"Background loop error: {err}")

async def post_init_hook(application):
    await start_web_server()
    now_slt = datetime.now(SLT_TZ).strftime("%Y-%m-%d %I:%M %p SLT")
    startup_msg = (
        "💎 *24/7 Cloud Analyzer & Recovery Engine Online*\n\n"
        f"• *Boot Time:* `{now_slt}`\n"
        "• *Data Analysis:* 24/7 Continuous (News & Volatility Filtered)\n"
        "• *Execution Window:* Mon–Fri, 1:30 PM – 9:30 PM SLT\n"
        "• *Weekend Guard:* MT5 Auto-Locked on Sat & Sun\n"
        "• *Loss Memory:* 3h Directional Lockout + 2.0R Recovery Mode"
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
    log.info("Initializing 24/7 Forex Cloud Analyzer & Recovery Engine...")
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
            interval=900,  # Runs every 15 minutes
            first=20
        )
        log.info("15-minute 24/7 analyzer & tracker loop scheduled.")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()