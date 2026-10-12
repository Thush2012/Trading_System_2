import os
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from core.scanner import LightweightScanner
from core.logger import setup_system_logger

log = setup_system_logger("TelegramBot")

# List of Forex pairs actively scanned
FOREX_PAIRS_DISPLAY = "EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, EURGBP, EURJPY, GBPJPY"

scanner = LightweightScanner()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["⚡ Scan Market Opportunities"],
            ["ℹ️ System Status"]
        ],
        resize_keyboard=True
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Dual Market Trade Engine Online*\n\n"
        "• *Deployment:* Active 24/7 Cloud (Render.com)\n"
        "• *Focus:* 100% Forex Major & Cross Pairs\n"
        "• *Auto Scan & TP/SL Tracker:* Active (15m Intervals)\n"
        "• *Milestone Alerts:* Automatic TP1, TP2, TP3 & SL Tracking\n"
        "• *Commands:* Listening for user interactions"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        "• *Engine:* Active Standalone (Render 24/7)\n"
        "• *Scheduler:* Running every 15 minutes\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Filters:* 200 EMA + ADX (>=20) + Dynamic ATR\n"
        "• *Dispatch Mode:* Direct Admin Only\n"
        "• *Cooldown:* 30 Mins per Pair Anti-Spam"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def scan_opportunities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scanning Forex market liquidity and higher-timeframe structures...*", parse_mode="Markdown")
    
    df = await scanner.scan_all(bypass_cooldown=True)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified Setups Active*\n\n"
            "All Forex pairs currently fail 200 EMA macro alignment or ADX momentum criteria (>=20).\n"
            "Patience protects capital.",
            parse_mode="Markdown"
        )
        return

    for _, row in df.iterrows():
        signal_msg = (
            f"⚡ *NEW FOREX SIGNAL: {row['symbol']}*\n"
            f"Direction: *{row['action']}*\n"
            f"Strategy: *{row['setup']}*\n\n"
            f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
            f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
            f"🎯 *Target 1 (1.0R):* `{row['tp1']}`\n"
            f"🎯 *Target 2 (1.8R):* `{row['tp2']}`\n"
            f"🎯 *Target 3 (2.6R):* `{row['tp3']}`\n\n"
            f"📊 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
            f"🕒 *Timestamp:* `{row['timestamp']}`\n\n"
            "⚠️ *Bonus Account Rule:* Strict 0.01 lot size per trade."
        )
        await update.message.reply_text(signal_msg, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚡ Scan Market Opportunities":
        await scan_opportunities(update, context)
    elif text == "ℹ️ System Status":
        await status_command(update, context)

def register_bot_handlers(application):
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("scan", scan_opportunities))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))