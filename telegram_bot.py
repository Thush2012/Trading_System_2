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
            ["🕒 Trading Hours", "🛡️ Risk Rules"]
        ],
        resize_keyboard=True
    )

def format_signal_message(row: dict) -> str:
    return (
        f"⚡ *NEW FOREX SIGNAL: {row['symbol']}*\n"
        f"Direction: *{row['action']}*\n"
        f"Strategy: *{row['setup']}*\n\n"
        f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
        f"🎯 *Take Profit:* `{row['tp']}` ({row['tp_pips']} pips)\n\n"
        f"📊 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
        f"🕒 *Timestamp:* `{row['timestamp']}`\n\n"
        "⚡ *Execution:* Pushed to Supabase for local MT5 auto-trade."
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Dual Market Trade Engine Online*\n\n"
        "• *Deployment:* Active 24/7 Cloud (Render.com)\n"
        "• *Mode:* Forex Auto-Signal + Supabase Bridge\n"
        "• *Target Model:* Single TP (1.5 ATR) / Hard SL\n"
        "• *Auto Scan:* Active (15m Intervals)\n"
        "• *Commands:* Listening for user interactions"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        "• *Engine:* Active Standalone (Render 24/7)\n"
        "• *Queue:* Supabase Live\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Targets:* Single TP (1:1 Risk/Reward)\n"
        "• *Lot Size:* 0.01 Fixed"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scanning Forex market liquidity...*", parse_mode="Markdown")
    df = await global_scanner.scan_all(bypass_cooldown=True)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified Setups Active*\n\n"
            "All Forex pairs currently fail 200 EMA macro alignment or ADX momentum criteria (>=20).\n"
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
        "• *Asian Session:* 5:30 AM – 2:30 PM (JPY pairs)\n"
        "• *London Session (Prime):* 12:30 PM – 9:30 PM (EUR/GBP pairs)\n"
        "• *NY / London Overlap (Peak):* 6:00 PM – 9:30 PM (Highest momentum)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_risk_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ *ACCOUNT RISK RULES*\n\n"
        "1. *Fixed Lot Size:* Strict 0.01 lots on every trade.\n"
        "2. *Single Target:* One clear TP at 1.5 ATR.\n"
        "3. *Hard Stop Loss:* Attached on order creation.\n"
        "4. *Max Exposure:* Max 2 open trades at any time."
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