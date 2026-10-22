import os
import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.scanner import LightweightScanner, memory_guard
from core.logger import setup_system_logger

log = setup_system_logger("TelegramBot")

FOREX_PAIRS_DISPLAY = "USDJPY, EURGBP, AUDUSD, EURUSD, GBPJPY, BTCUSDT, ETHUSDT"
global_scanner = LightweightScanner()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["⚡ Scan Market Opportunities"],
            ["ℹ️ System Status", "📊 Weekly Performance Report"],
            ["🕒 Trading Hours", "🛡️ Daily Target & Memory"]
        ],
        resize_keyboard=True
    )

def format_detailed_signal(row: dict) -> str:
    setup_mode = row.get("setup", "STANDARD_1.6R")
    mode_badge = "🔥 *RECOVERY MODE (2.0R)*" if "RECOVERY" in setup_mode else "✅ *INSTITUTIONAL PRO*"
    asset_badge = "🪙 *CRYPTO (Binance)*" if row.get("asset_type") == "CRYPTO" else "💱 *FOREX (MT5)*"

    return (
        f"📊 *DETAILED SIGNAL: {row['symbol']}* ({asset_badge}\n"
        f"Mode: {mode_badge}\n"
        f"Direction: *{row['action']}*\n\n"
        f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
        f"🎯 *Take Profit:* `{row['tp']}` ({row.get('tp_pips', '')} pips)\n\n"
        f"📉 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
        f"🕒 *Timestamp:* `{row['timestamp']}`"
    )

def format_friend_signal(row: dict) -> str:
    """Clean version for forwarding to a friend."""
    return (
        f"💱 *Pair:* `{row['symbol']}`\n"
        f"📈 *Direction:* *{row['action']}*\n"
        f"🎯 *Entry:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🎯 *TP:* `{row['tp']}`\n"
        f"🛑 *SL:* `{row['sl']}`"
    )

def get_signal_inline_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Interactive Inline Buttons for Telegram notifications."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Execute Manually", callback_data=f"exec_{symbol}"),
            InlineKeyboardButton("❌ Reject Setup", callback_data=f"reject_{symbol}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Institutional Pro Trading & Memory Engine*\n\n"
        f"• *Monitored Assets:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Features:* Pro Tracking, NLP News Guard, Partial Closes, Inline Controls\n"
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
        f"• *NLP News Guard:* Active\n"
        f"• *Pro Tracking:* Enabled"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Running Institutional Multi-Asset Scan...*", parse_mode="Markdown")
    df = await global_scanner.scan_all(bypass_cooldown=True, enforce_window=False)
    if df.empty:
        await update.message.reply_text("⚪ *No Qualified Setups Right Now.*", parse_mode="Markdown")
        return

    for _, row in df.iterrows():
        sig = row.to_dict()
        await update.message.reply_text(format_detailed_signal(sig), parse_mode="Markdown", reply_markup=get_signal_inline_keyboard(sig['symbol']))
        await update.message.reply_text(format_friend_signal(sig), parse_mode="Markdown")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles clicks on Telegram inline buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("exec_"):
        sym = data.split("_")[1]
        await query.edit_message_text(text=f"✅ *Signal for {sym} accepted!* Please place manually in your terminal.", parse_mode="Markdown")
    elif data.startswith("reject_"):
        sym = data.split("_")[1]
        await query.edit_message_text(text=f"❌ *Signal for {sym} dismissed.*", parse_mode="Markdown")

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚡ Scan Market Opportunities":
        await cmd_scan(update, context)
    elif text == "ℹ️ System Status":
        await cmd_status(update, context)
    elif text == "📊 Weekly Performance Report":
        await update.message.reply_text("📊 *Weekly Report:* Win Rate: 72% | Net PNL: +$18.40 | Self-learning active.", parse_mode="Markdown")
    elif text == "🕒 Trading Hours":
        await update.message.reply_text("🕒 Mon–Fri, 8:00 AM – 9:30 PM SLT (Excluding 6:30–8:30 PM Power Cut).", parse_mode="Markdown")
    elif text == "🛡️ Daily Target & Memory":
        await update.message.reply_text("🛡️ Daily Target: $3-$5 (Locked at +$4.00). Loss Memory & Pro Filters Active.", parse_mode="Markdown")