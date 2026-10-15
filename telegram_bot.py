import os
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from core.scanner import LightweightScanner
from core.logger import setup_system_logger

log = setup_system_logger("TelegramBot")

FOREX_PAIRS_DISPLAY = "EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, EURGBP, EURJPY, GBPJPY"
global_scanner = LightweightScanner()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["⚡ Scan Market Opportunities"],
            ["ℹ️ System Status"],
            ["🕒 Trading Sessions", "🛡️ High-Accuracy Rules"]
        ],
        resize_keyboard=True
    )

def format_signal_message(row: dict) -> str:
    feed = row.get("source", "Live MT5")
    spread = row.get("spread_pips", "Normal")

    return (
        f"⚡ *HIGH ACCURACY FOREX SIGNAL: {row['symbol']}*\n"
        f"Direction: *{row['action']}*\n"
        f"Strategy: *{row['setup']}*\n\n"
        f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
        f"🎯 *Target 1 (1.2R):* `{row['tp1']}` ({row.get('tp1_pips', '')} pips)\n"
        f"🎯 *Target 2 (2.0R):* `{row['tp2']}`\n"
        f"🎯 *Target 3 (3.0R):* `{row['tp3']}`\n\n"
        f"📊 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
        f"📡 *Data Feed:* `{feed}` | Spread: `{spread} pips`\n"
        f"🕒 *Timestamp:* `{row['timestamp']}`\n\n"
        "💡 *Rule:* 0.01 lot size. Move Stop Loss to Entry when Target 1 is hit."
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Precision Forex Trade Engine Online*\n\n"
        "• *Engine:* Active 24/5 Direct Cloud/Terminal\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Filter Core:* H1 Macro Trend + M15 Candlestick Rejection\n"
        "• *Target Model:* Multi-tier (TP1 Breakeven Trigger, TP2/TP3 Runners)\n"
        "• *Scheduler:* Scanning every 15 minutes"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed_type = "MT5 Direct Terminal" if global_scanner.mt5_initialized else "Web Fallback Engine"

    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        f"• *Data Feed:* {feed_type}\n"
        "• *Operation Mode:* 24/5 High-Accuracy Continuous Scan\n"
        "• *Scan Cycle:* Every 15 Minutes\n"
        f"• *Monitored Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Filters:* H1/M15 Dual EMA 200, ADX Momentum, Rejection Wick Confirmation\n"
        "• *Min Target:* 14.0 Pips"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scanning institutional liquidity and H1/M15 rejection setups...*", parse_mode="Markdown")

    df = await global_scanner.scan_all(bypass_cooldown=True, enforce_window=False)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified High-Accuracy Setups Active*\n\n"
            "All pairs currently fail H1/M15 dual trend alignment or EMA rejection criteria.\n"
            "Filtering out bad entries is what protects your win rate.",
            parse_mode="Markdown"
        )
        return

    for _, row in df.iterrows():
        msg = format_signal_message(row.to_dict())
        await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_trading_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🕒 *OPTIMAL TRADING SESSIONS (SLT / UTC+5:30)*\n\n"
        "• *London Session (1:30 PM – 5:30 PM):* High breakout follow-through.\n"
        "• *London/NY Overlap (5:30 PM – 9:30 PM):* Peak liquidity and tightest spreads.\n"
        "• *Asian Session (5:30 AM – 1:30 PM):* JPY and AUD pairs only.\n\n"
        "💡 *Note:* The scanner operates 24/5 but only triggers when institutional trend rules are met."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_risk_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ *DAILY TARGET & RISK RULES*\n\n"
        "• *Lot Size:* 0.01 lot fixed.\n"
        "• *Daily Target:* 2 to 3 winning setups = +$3.00 to +$6.00 profit.\n"
        "• *Exposure Limit:* Maximum 2 open trades at any time.\n"
        "• *Breakeven Rule:* As soon as Target 1 is hit, drag Stop Loss to Entry price.\n"
        "• *Discipline:* Never remove or widen a Stop Loss."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚡ Scan Market Opportunities":
        await cmd_scan(update, context)
    elif text == "ℹ️ System Status":
        await cmd_status(update, context)
    elif text == "🕒 Trading Sessions":
        await cmd_trading_hours(update, context)
    elif text == "🛡️ High-Accuracy Rules":
        await cmd_risk_rules(update, context)