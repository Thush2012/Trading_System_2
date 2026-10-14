import os
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from core.scanner import LightweightScanner
from core.logger import setup_system_logger

log = setup_system_logger("TelegramBot")

FOREX_PAIRS_DISPLAY = "EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, EURGBP, EURJPY, GBPJPY"
TIMEFRAMES_DISPLAY = "5m (Scalp), 15m (Intraday), 1h (Macro Trend)"

global_scanner = LightweightScanner()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["⚡ Scan Market Opportunities"],
            ["ℹ️ System Status"],
            ["🕒 Timeframe Breakdown", "🛡️ Daily Targets & Rules"]
        ],
        resize_keyboard=True
    )

def format_signal_message(row: dict) -> str:
    feed = row.get("source", "Live MT5")
    tf = row.get("timeframe", "15m").upper()
    strat = row.get("strategy_type", "INTRADAY")
    spread = row.get("spread_pips", "Normal")

    return (
        f"⚡ *NEW FOREX SIGNAL: {row['symbol']} [{tf}]*\n"
        f"Direction: *{row['action']}*\n"
        f"Profile: *{strat} (Dual MTF Alignment)*\n\n"
        f"📍 *Entry Zone:* `{row['entry_low']} - {row['entry_high']}`\n"
        f"🛑 *Stop Loss:* `{row['sl']}` ({row['sl_pips']} pips)\n"
        f"🎯 *Target 1 (Base):* `{row['tp1']}` ({row.get('tp1_pips', '')} pips)\n"
        f"🎯 *Target 2 (Runner):* `{row['tp2']}`\n"
        f"🎯 *Target 3 (Max):* `{row['tp3']}`\n\n"
        f"📊 *Indicators:* RSI `{row['rsi']}` | ADX `{row['adx']}`\n"
        f"📡 *Feed:* `{feed}` | Spread: `{spread} pips`\n"
        f"🕒 *Timestamp:* `{row['timestamp']}`\n\n"
        "💡 *Rule:* 0.01 lot per position. Move SL to Breakeven at Target 1."
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Multi-Timeframe Forex Engine Online*\n\n"
        "• *Engine:* Active 24/5 Direct Cloud/Terminal\n"
        f"• *Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        f"• *Scanning Horizons:* {TIMEFRAMES_DISPLAY}\n"
        "• *Strategy:* Dual MTF Structure + EMA Pullback\n"
        "• *Target Model:* 3-Tier Targets with Automated Breakeven\n"
        "• *Scheduler:* Scanning every 5 minutes"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed_type = "MT5 Direct Terminal" if global_scanner.mt5_initialized else "Web Fallback Engine"

    msg = (
        "ℹ️ *SYSTEM STATUS*\n"
        f"• *Data Feed:* {feed_type}\n"
        "• *Operation Mode:* 24/5 Continuous Multi-Timeframe Scan\n"
        f"• *Timeframes:* 5m (Scalp), 15m (Intraday), 1h (Trend)\n"
        f"• *Monitored Pairs:* {FOREX_PAIRS_DISPLAY}\n"
        "• *Filters:* ADX Momentum, Dual MTF 200 EMA, Dynamic ATR\n"
        "• *Scan Cycle:* Every 5 Minutes"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scanning 5m, 15m, and 1h institutional liquidity across all 9 pairs...*", parse_mode="Markdown")

    df = await global_scanner.scan_all(bypass_cooldown=True, enforce_window=False)
    if df.empty:
        await update.message.reply_text(
            "⚪ *No Qualified Multi-Timeframe Setups Active*\n\n"
            "All pairs across 5m, 15m, and 1h are currently consolidating or failing macro trend alignment.\n"
            "Patience protects capital.",
            parse_mode="Markdown"
        )
        return

    for _, row in df.iterrows():
        msg = format_signal_message(row.to_dict())
        await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_trading_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🕒 *MULTI-TIMEFRAME SCANNING BREAKDOWN*\n\n"
        "• *5m Scalps:* Active throughout London & NY sessions; targets quick 8–15 pip moves.\n"
        "• *15m Intraday:* Standard momentum setups; targets 12–25 pips.\n"
        "• *1h Macro Trends:* High-conviction swing runs; targets 25–50+ pips.\n\n"
        "💡 *Note:* The scanner evaluates all 3 timeframes every 5 minutes."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def cmd_risk_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🛡️ *DAILY $5–$10 TARGET & RISK RULES*\n\n"
        "• *At 0.01 Lot:* 1 pip ≈ $0.10\n"
        "• *Target Math:* 50 to 100 net pips/day = $5 to $10 profit.\n"
        "1. *Fixed Lot Size:* Strict 0.01 lots on every execution.\n"
        "2. *Max Open Trades:* Maximum 2 open trades simultaneously.\n"
        "3. *Target 1 Action:* Move Stop Loss to Entry (Breakeven) as soon as TP1 hits.\n"
        "4. *Stop Out Discipline:* Never adjust or widen a Stop Loss after entering."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚡ Scan Market Opportunities":
        await cmd_scan(update, context)
    elif text == "ℹ️ System Status":
        await cmd_status(update, context)
    elif text == "🕒 Timeframe Breakdown":
        await cmd_trading_hours(update, context)
    elif text == "🛡️ Daily Targets & Rules":
        await cmd_risk_rules(update, context)