import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from core.scanner import LightweightScanner, memory_guard
from core.logger import setup_system_logger

log = setup_system_logger("TelegramBot")

FOREX_PAIRS_DISPLAY = "USDJPY, EURGBP, AUDUSD, EURUSD, GBPJPY"
global_scanner = LightweightScanner()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["⚡ Scan Market Opportunities"],
            ["ℹ️ System Status"],
            ["🕒 Trading Hours", "🛡️ Daily Target & Memory"]
        ],
        resize_keyboard=True
    )

def format_detailed_signal(row: dict) -> str:
    """Style 1: Full detailed signal for your tracking."""
    setup_mode = row.get("setup", "STANDARD_1.6R")
    mode_badge = "🔥 *RECOVERY MODE (2.0R)*" if "RECOVERY" in setup_mode else "✅ *STANDARD MODE (1.6R)*"

    return (
        f"📊 *DETAILED SIGNAL: {row['symbol']}*\n"
        f"Mode: {mode_badge}\n"
        f"Direction: *{row['action']}*\n\n"
        f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
        f"🎯 *Take Profit:* `{row['tp']}` ({row.get('tp_pips', '')} pips)\n\n"
        f"📉 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
        f"🕒 *Timestamp:* `{row['timestamp']}`"
    )

def format_friend_signal(row: dict) -> str:
    """Style 2: Clean, short version to copy and forward to a friend."""
    return (
        f"💱 *Pair:* `{row['symbol']}`\n"
        f"📈 *Direction:* *{row['action']}*\n"
        f"🎯 *Entry:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🎯 *TP:* `{row['tp']}`\n"
        f"🛑 *SL:* `{row['sl']}`"
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Precision Forex Engine Online*\n\n"
        f"• *Monitored Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Signal Output:* Dual Format (Detailed + Friend-Share Version)\n"
        "• *Execution Window:* Mon–Fri, 8:00 AM – 9:30 PM SLT"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    in_window = global_scanner.is_within_trading_window()
    state_str = "🟢 EXECUTION ACTIVE" if in_window else "⏸️ STANDBY"
    rec_active = memory_guard.state.get("in_recovery", False)
    deficit = memory_guard.state.get("deficit_usd", 0.0)
    rec_str = f"🔥 Active (Deficit: ${deficit:.2f})" if rec_active else "✅ Normal"

    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        f"• *State:* {state_str}\n"
        f"• *Recovery Status:* {rec_str}\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Dual Formatting:* Enabled (Sends 2 messages per signal)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scanning and generating dual-format signals...*", parse_mode="Markdown")

    df = await global_scanner.scan_all(bypass_cooldown=True, enforce_window=False)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified Setups Right Now*\n\nPatience protects capital.",
            parse_mode="Markdown"
        )
        return

    for _, row in df.iterrows():
        signal_data = row.to_dict()
        await update.message.reply_text(format_detailed_signal(signal_data), parse_mode="Markdown")
        await update.message.reply_text(format_friend_signal(signal_data), parse_mode="Markdown")

async def cmd_trading_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🕒 *Operating Window:* Mon–Fri, 8:00 AM – 9:30 PM SLT (Excluding 6:30–8:30 PM Power Cut)."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_risk_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🛡️ *Rule:* Fixed 0.01 lot size, Asymmetric R:R, Loss Memory Active."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚡ Scan Market Opportunities":
        await cmd_scan(update, context)
    elif text == "ℹ️ System Status":
        await cmd_status(update, context)
    elif text == "🕒 Trading Hours":
        await cmd_trading_hours(update, context)
    elif text == "🛡️ Daily Target & Memory":
        await cmd_risk_rules(update, context)