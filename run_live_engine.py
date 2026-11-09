import asyncio
from datetime import UTC, datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

from core.config import Config
from core.executor import ExecutionEngine
from core.logger import setup_system_logger
from core.mt5_connection import connect_mt5
from core.news_filter import EconomicCalendarShield
from core.notifier import TelegramNotifier
from core.risk_manager import RiskManager
from core.scanner import MultiTimeframeScanner

log = setup_system_logger("LiveEngine")

# Memory caches to avoid duplicate Telegram notifications
NOTIFIED_DEALS = set()
NOTIFIED_SURGES = set()
LAST_ALERTED_OPPORTUNITIES = {}

def audit_unrealized_profit_surges(notifier: TelegramNotifier):
    """Monitors active open positions and pushes an alert when a trade spikes into big profit."""
    if not connect_mt5():
        return
        
    account = mt5.account_info()
    positions = mt5.positions_get()
    
    if not account or not positions:
        return
        
    # Surge threshold: +0.2% of account equity or minimum $10
    surge_threshold = max(account.equity * 0.002, 10.0)

    for pos in positions:
        if pos.profit >= surge_threshold and pos.ticket not in NOTIFIED_SURGES:
            NOTIFIED_SURGES.add(pos.ticket)
            msg = (
                f"⚡ *SUDDEN PROFIT SURGE DETECTED* ⚡\n\n"
                f"• Pair: `{pos.symbol}`\n"
                f"• Floating Profit: *+${pos.profit:,.2f}*\n"
                f"• Ticket: `{pos.ticket}`\n\n"
                f"💡 _Send `/closeall` to lock in profit immediately, or allow trailing stop to manage it._"
            )
            log.info(msg)
            notifier.send_alert(msg)

def audit_closed_trades(notifier: TelegramNotifier):
    """Audits closed orders and reports realized profit wins or stop hits."""
    if not connect_mt5():
        return

    now = datetime.now(UTC)
    deals = mt5.history_deals_get(now - timedelta(hours=2), now)

    if not deals:
        return

    for deal in deals:
        if deal.entry == 1 and deal.ticket not in NOTIFIED_DEALS:
            NOTIFIED_DEALS.add(deal.ticket)
            pnl = deal.profit
            symbol = deal.symbol
            if pnl > 0:
                msg = (
                    f"🎉 *PROFIT TARGET HIT (WIN)* 🎉\n"
                    f"• Symbol: `{symbol}`\n"
                    f"• Realized Win: *+${pnl:,.2f}*\n"
                    f"• Deal Ticket: `{deal.ticket}`"
                )
                log.info(msg)
                notifier.send_alert(msg)
            elif pnl < 0:
                msg = (
                    f"🛑 *STOP LOSS HIT*\n"
                    f"• Symbol: `{symbol}`\n"
                    f"• Realized Loss: *-${abs(pnl):,.2f}*\n"
                    f"• Deal Ticket: `{deal.ticket}`"
                )
                log.info(msg)
                notifier.send_alert(msg)

def has_open_forex_position(symbol: str) -> bool:
    """Checks whether an open position already exists for the given symbol."""
    if not connect_mt5():
        return False
    positions = mt5.positions_get(symbol=symbol)
    return positions is not None and len(positions) > 0

async def run_trading_cycle():
    """Main execution cycle across Forex and Crypto."""
    # Ensure background MT5 process is active
    if not connect_mt5():
        log.warning("MT5 background link not established. Skipping cycle.")
        return

    scanner = MultiTimeframeScanner(
        forex_symbols=Config.FOREX_WATCHLIST,
        crypto_symbols=Config.CRYPTO_WATCHLIST,
        timeframes=["5m", "15m", "1h"]
    )
    risk = RiskManager(
        risk_per_trade_pct=Config.RISK_PER_TRADE_PCT,
        max_daily_drawdown_pct=Config.MAX_DAILY_DRAWDOWN_PCT
    )
    executor = ExecutionEngine()
    notifier = TelegramNotifier(bot_token=Config.TELEGRAM_BOT_TOKEN, chat_id=Config.TELEGRAM_CHAT_ID)
    news_shield = EconomicCalendarShield(buffer_minutes=30)

    try:
        # Check active floating profit spikes & recently closed deals
        audit_closed_trades(notifier)
        audit_unrealized_profit_surges(notifier)

        # Stage 1: Trailing stop auto-management
        for sym in Config.FOREX_WATCHLIST:
            adjustments = executor.manage_open_positions(
                sym, 
                breakeven_pips=Config.BREAKEVEN_PIPS, 
                trail_distance_pips=Config.TRAIL_DISTANCE_PIPS
            )
            for note in adjustments:
                log.info(note)
                notifier.send_alert(note)

        # Stage 2: Multi-timeframe scan (5m, 15m, 1h with 4H Trend Alignment)
        log.info("Running automated market opportunity scan...")
        report = await scanner.scan_all()

        if report.empty:
            log.info("Scan completed: no data returned.")
            return

        # Stage 3: Opportunity detection & order execution
        now_ts = datetime.now()

        for _, row in report.iterrows():
            action = row["action"]
            symbol = row["symbol"]
            tf = row["timeframe"]
            entry = row["entry"]
            sl = row["stop_loss"]
            tp = row["take_profit"]
            macro = row.get("macro_bias", "ANY")
            is_surge = row.get("is_sudden_surge", False)
            asset_class = row["asset_class"]

            if action in ["🟢 BUY", "🔴 SELL"] and pd.notna(sl) and pd.notna(tp):
                clean_action = "BUY" if "BUY" in action else "SELL"

                # 1. Economic News Calendar Shield
                safe, reason = news_shield.is_safe_to_trade(symbol)
                if not safe:
                    log.warning(f"Order aborted for {symbol} ({tf}): {reason}")
                    continue

                if asset_class == "FOREX":
                    # Throttle notification: max 1 notification per pair/tf per hour
                    alert_key = f"{symbol}_{tf}_{action}"
                    last_time = LAST_ALERTED_OPPORTUNITIES.get(alert_key)
                    if last_time and (now_ts - last_time).total_seconds() < 3600:
                        continue

                    symbol_info = mt5.symbol_info(symbol)
                    account = mt5.account_info()
                    equity = account.equity if account else 10000.0

                    # 2. Dynamic Spread Check
                    if symbol_info is not None:
                        current_spread = symbol_info.spread
                        if current_spread > Config.MAX_FOREX_SPREAD_POINTS:
                            log.warning(f"Execution rejected for {symbol}: Spread too wide ({current_spread} pts > {Config.MAX_FOREX_SPREAD_POINTS} max).")
                            continue

                    plan = risk.evaluate_forex_stake(equity, entry, sl, tp, symbol_info)

                    # Send rich opportunity alert to Telegram
                    surge_badge = "🔥 *SUDDEN VOLATILITY BREAKOUT* 🔥\n" if is_surge else "🎯 *HIGH-PROBABILITY SETUP IDENTIFIED* 🎯\n"
                    opp_msg = (
                        f"{surge_badge}"
                        f"• Asset: `{symbol}` ({action})\n"
                        f"• Timeframe: *{tf} Chart*\n"
                        f"• 4H Macro Trend: *{macro}*\n\n"
                        f"💰 *Stake Allocation:*\n"
                        f"• Equity: `${equity:,.2f}`\n"
                        f"• Recommended Stake: *{plan['lot_size']} Lots*\n"
                        f"• Entry: `{entry}`\n"
                        f"• Stop Loss: `{sl}` (Risk: -${plan['risk_usd']:,.2f})\n"
                        f"• Take Profit: `{tp}` (Win Target: *+${plan['projected_profit_usd']:,.2f}*)\n"
                        f"• Risk/Reward: `1:{plan['rr_ratio']}`\n\n"
                        f"⏱ _Timing: Setup confirmed by 4H macro trend._"
                    )
                    log.info(f"Dispatched opportunity alert for {symbol} ({tf})")
                    notifier.send_alert(opp_msg)
                    LAST_ALERTED_OPPORTUNITIES[alert_key] = now_ts

                    # 3. Auto-Execution if position is not already active
                    if not has_open_forex_position(symbol):
                        point = symbol_info.point if symbol_info else 0.00001
                        sl_points = int(abs(entry - sl) / point)
                        tp_points = int(abs(tp - entry) / point)

                        order_res = executor.place_forex_order(
                            symbol, 
                            clean_action, 
                            plan["lot_size"], 
                            sl_points=sl_points, 
                            tp_points=tp_points
                        )

                        if order_res.get("status") == "success":
                            exec_msg = (
                                f"🚀 *Trade Executed ({tf})*\n"
                                f"• Pair: `{symbol}` ({clean_action})\n"
                                f"• Macro Trend (4h): `{macro}`\n"
                                f"• Volume: *{plan['lot_size']} Lots*\n"
                                f"• Entry: `{order_res['entry_price']}`\n"
                                f"• Stop Loss: `{sl}` (-${plan['risk_usd']:,.2f})\n"
                                f"• Take Profit: `{tp}` (*+${plan['projected_profit_usd']:,.2f}*)\n"
                                f"• Spread at Entry: `{symbol_info.spread} pts`\n"
                                f"• R/R: 1:{plan['rr_ratio']}"
                            )
                            log.info(exec_msg)
                            notifier.send_alert(exec_msg)

    finally:
        await scanner.close()
        await executor.close()

if __name__ == "__main__":
    asyncio.run(run_trading_cycle())