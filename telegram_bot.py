import os
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from core.scanner import LightweightScanner
from core.logger import setup_system_logger

log = setup_system_logger("TelegramBot")

# Dedicated Forex watchlist display
FOREX_PAIRS_DISPLAY = "EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, EURGBP, EURJPY, GBPJPY"

# Shared global scanner instance imported by main.py
global_scanner = LightweightScanner()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["⚡ Scan Market Opportunities"],
            ["ℹ️ System Status"],
            ["🕒 Trading Hours", "🛡️ Risk Rules"]
        ],
        resize_keyboard=True
    )

def format_signal_message(row: dict) -> str:
    """Formats a signal row/dict into a standardized Telegram broadcast message."""
    return (
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

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Dual Market Trade Engine Online*\n\n"
        "• *Deployment:* Active 24/7 Cloud (Render.com)\n"
        "• *Focus:* 100% Forex Major & Cross Pairs\n"
        "• *Active Window:* 1:30 PM – 9:30 PM (Sri Lanka Time)\n"
        "• *Auto Scan & TP/SL Tracker:* Active (15m Intervals)\n"
        "• *Milestone Alerts:* Automatic TP1, TP2, TP3 & SL Tracking\n"
        "• *Commands:* Listening for user interactions"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    in_window = global_scanner.is_within_trading_window()
    status_state = "🟢 ACTIVE (In Window)" if in_window else "⏸️ STANDBY (Outside Hours)"

    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        "• *Engine:* Active Standalone (Render 24/7)\n"
        f"• *Current State:* {status_state}\n"
        "• *Active Window:* 1:30 PM – 9:30 PM SLT (UTC+5:30)\n"
        "• *Scheduler:* Running every 15 minutes\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Filters:* Dual MTF (H1+M15) + ADX (>=25 Rising) + EMA Pullback\n"
        "• *Dispatch Mode:* Direct Admin Only\n"
        "• *Cooldown:* 30 Mins per Pair Anti-Spam"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scanning Forex market liquidity and higher-timeframe structures...*", parse_mode="Markdown")

    if not global_scanner.is_within_trading_window():
        await update.message.reply_text(
            "⏸️ *Outside Scheduled Trading Hours*\n\n"
            "Active Signal Window is strictly locked to:\n"
            "🕒 *1:30 PM – 9:30 PM (Sri Lanka Time)*\n\n"
            "This protects against low liquidity periods and frees up your morning and night for other work.",
            parse_mode="Markdown"
        )
        return

    df = await global_scanner.scan_all(bypass_cooldown=True, enforce_window=False)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified Setups Active*\n\n"
            "All Forex pairs currently fail Dual MTF (H1+M15 200 EMA), Pullback, or ADX >= 25 criteria.\n"
            "Patience protects capital.",
            parse_mode="Markdown"
        )
        return

    for _, row in df.iterrows():
        msg = format_signal_message(row.to_dict())
        await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_trading_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🕒 *KEY TRADING WINDOWS (GMT+5:30 Sri Lanka)*\n\n"
        "• *Scheduled Signal Window:* 1:30 PM – 9:30 PM\n"
        "  └ *London Open:* 1:30 PM – 5:30 PM (High institutional trend moves)\n"
        "  └ *London/NY Overlap:* 5:30 PM – 9:30 PM (Peak daily volume & tightest spreads)\n\n"
        "• *Outside Hours (Silent Standby):*\n"
        "  └ 9:30 PM – 1:30 PM next day (Allows you to focus on your day tasks with zero interruptions)."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_risk_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ *BONUS ACCOUNT RISK MANAGEMENT*\n\n"
        "1. *Fixed Lot Size:* Strict 0.01 lots on every trade.\n"
        "2. *Entry Confirmation:* Enter only within the highlighted Entry Zone.\n"
        "3. *Hard Stop Loss:* Place SL immediately upon entry.\n"
        "4. *TP1 Breakeven:* Move SL to Breakeven when TP1 is hit; ride TP2/TP3.\n"
        "5. *Max Exposure:* Maximum 2 simultaneous open positions."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚡ Scan Market Opportunities":
        await cmd_scan(update, context)
    elif text == "ℹ️ System Status":
        await cmd_status(update, context)
    elif text == "🕒 Trading Hours":
        await cmd_trading_hours(update, context)
    elif text == "🛡️ Risk Rules":
        await cmd_risk_rules(update, context)