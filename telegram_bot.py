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

def format_signal_message(row: dict) -> str:
    setup_mode = row.get("setup", "STANDARD_1.6R")
    mode_badge = "🔥 *RECOVERY MODE (2.0R)*" if "RECOVERY" in setup_mode else "✅ *STANDARD MODE (1.6R)*"

    return (
        f"⚡ *FOREX SIGNAL: {row['symbol']}*\n"
        f"Mode: {mode_badge}\n"
        f"Direction: *{row['action']}*\n\n"
        f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
        f"🎯 *Take Profit:* `{row['tp']}` ({row.get('tp_pips', '')} pips)\n\n"
        f"📊 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
        f"🕒 *Timestamp:* `{row['timestamp']}`\n\n"
        "🤖 *Auto-Execution:* Dispatched to Supabase for local MT5 (0.01 Lot)."
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *24/7 Cloud Analyzer & Auto-Recovery Engine*\n\n"
        f"• *Monitored Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Cloud Analysis:* 24/7 Continuous (News & Spike Filtered)\n"
        "• *Execution Window:* Mon–Fri, 8:00 AM – 9:30 PM SLT *(Excluding 6:30–8:30 PM Power Cut)*\n"
        "• *Daily Profit Lock:* +$3.00 to +$5.00 (Locked at +$4.00)\n"
        "• *Loss Memory:* 3h Directional Lockout + 2.0R Recovery"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    in_window = global_scanner.is_within_trading_window()
    state_str = "🟢 EXECUTION ACTIVE (8:00 AM - 9:30 PM SLT)" if in_window else "⏸️ STANDBY (Outside Hours / Power Cut Block)"
    rec_active = memory_guard.state.get("in_recovery", False)
    deficit = memory_guard.state.get("deficit_usd", 0.0)
    rec_str = f"🔥 Active (Deficit: ${deficit:.2f} | Target: 2.0R)" if rec_active else "✅ Normal (Target: 1.6R)"

    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        f"• *State:* {state_str}\n"
        f"• *Recovery Status:* {rec_str}\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Daily Profit Goal:* $3.00 – $5.00 (Locked at +$4.00)\n"
        "• *Operating Window:* 8:00 AM – 9:30 PM SLT (Excluding 6:30–8:30 PM Power Cut)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Analyzing market structure across high-expectancy pairs...*", parse_mode="Markdown")

    df = await global_scanner.scan_all(bypass_cooldown=True, enforce_window=False)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified Setups Right Now*\n\n"
            "All pairs currently fail H1+M15 alignment, ADX momentum, or are locked by the Loss Memory Engine.\n"
            "Patience protects your daily target.",
            parse_mode="Markdown"
        )
        return

    for _, row in df.iterrows():
        msg = format_signal_message(row.to_dict())
        await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_trading_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🕒 *OPERATING SCHEDULE (SRI LANKA TIME)*\n\n"
        "• *24/7 Cloud Analysis:* Runs continuously to track EMAs, ADX, and news volatility.\n"
        "• *Active Trade Window:* Monday – Friday, *8:00 AM – 9:30 PM SLT*.\n"
        "• *Power Cut Blackout:* Completely locked out between *6:30 PM – 8:30 PM SLT* (No Wi-Fi/Power).\n"
        "• *Weekend Lock:* Completely disabled on Saturday & Sunday so MT5 never opens."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_risk_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ *DAILY $3–$5 PROFIT & MEMORY RULES*\n\n"
        "1. *Daily Goal Lock:* Executor automatically stops opening new trades once +$4.00 is banked for the day.\n"
        "2. *Asymmetric R:R:* SL = 1.2x ATR | Standard TP = 1.6x ATR.\n"
        "3. *Loss Memory:* If a setup hits SL, that pair & direction is banned for 3 hours.\n"
        "4. *Recovery Mode:* After a loss, lot stays 0.01, required ADX increases to 28, and TP expands to 2.0x ATR."
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
    elif text == "🛡️ Daily Target & Memory":
        await cmd_risk_rules(update, context)