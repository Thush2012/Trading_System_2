import asyncio
import time

import MetaTrader5 as mt5
import streamlit as st

from core.backtester import Backtester
from core.config import Config
from core.data_fetcher import UnifiedDataFetcher
from core.mt5_connection import connect_mt5
from core.scanner import MultiTimeframeScanner

st.set_page_config(
    page_title="Dual-Market Trading Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Header Section
st.title("📈 Dual-Market Trading Terminal")
st.caption("Live Multi-Timeframe Signals, Macro Trend Alignment & Backtesting Engine")

# Auto-refresh banner and connection status
timestamp_col, status_col = st.columns([3, 1])
with timestamp_col:
    st.info(f"🕒 **Last Synchronized:** `{time.strftime('%Y-%m-%d %H:%M:%S')}` (Terminal auto-refreshes every 60s)")
with status_col:
    # Use headless background connection
    if connect_mt5():
        acc = mt5.account_info()
        st.success(f"🟢 Headless MT5 Linked | Equity: **${acc.equity:,.2f}**" if acc else "🟢 Headless MT5 Linked")
    else:
        st.warning("🟡 MT5 Standby / Connecting...")

tab1, tab2 = st.tabs(["🔍 Live Market Radar", "📊 Strategy Backtester"])

# --- TAB 1: RADAR SCANNER ---
with tab1:
    st.subheader("Multi-Timeframe Radar (5m, 15m, 1h with 4H Trend Alignment)")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        manual_scan = st.button("🔄 Force Refresh Scan", use_container_width=True)

    with st.spinner("Analyzing candles across 5m, 15m, 1h and 4H 200 EMA..."):
        async def fetch_scan_data():
            scanner = MultiTimeframeScanner(
                forex_symbols=Config.FOREX_WATCHLIST,
                crypto_symbols=Config.CRYPTO_WATCHLIST,
                timeframes=["5m", "15m", "1h"]
            )
            report = await scanner.scan_all()
            await scanner.close()
            return report

        df_report = asyncio.run(fetch_scan_data())

        if not df_report.empty:
            # Highlight immediate opportunities
            active_signals = df_report[df_report["action"].isin(["🟢 BUY", "🔴 SELL"])]
            
            if not active_signals.empty:
                st.markdown("### 🎯 Immediate Opportunities Detected")
                for _, row in active_signals.iterrows():
                    badge = "🔥 **Sudden Volatility Breakout**" if row.get("is_sudden_surge") else "⭐ **Standard Setup**"
                    st.success(
                        f"{badge} | **{row['symbol']}** ({row['timeframe']}) — **{row['action']}** | "
                        f"Entry: `{row['entry']}` | Stop Loss: `{row['stop_loss']}` | Take Profit: `{row['take_profit']}` | "
                        f"4H Macro: `{row.get('macro_bias', 'N/A')}` | RSI: `{row['rsi']}`"
                    )

            st.markdown("### 📋 Complete Watchlist Matrix")
            st.dataframe(
                df_report,
                column_config={
                    "asset_class": st.column_config.TextColumn("Asset"),
                    "symbol": st.column_config.TextColumn("Symbol"),
                    "timeframe": st.column_config.TextColumn("TF"),
                    "macro_bias": st.column_config.TextColumn("4H Macro"),
                    "action": st.column_config.TextColumn("Signal"),
                    "entry": st.column_config.NumberColumn("Entry Price", format="%.5f"),
                    "stop_loss": st.column_config.NumberColumn("Stop Loss", format="%.5f"),
                    "take_profit": st.column_config.NumberColumn("Take Profit", format="%.5f"),
                    "rsi": st.column_config.NumberColumn("RSI (14)", format="%.2f"),
                    "is_sudden_surge": st.column_config.CheckboxColumn("Surge?"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No scan records generated. Ensure data sources are reachable.")

# --- TAB 2: BACKTESTER ---
with tab2:
    st.subheader("Historical Parameter Backtester")
    col_a, col_b, col_c = st.columns(3)
    
    with col_a:
        asset_type = st.selectbox("Asset Class", ["FOREX", "CRYPTO"])
    with col_b:
        symbol = st.selectbox(
            "Symbol",
            Config.FOREX_WATCHLIST if asset_type == "FOREX" else Config.CRYPTO_WATCHLIST
        )
    with col_c:
        tf = st.selectbox("Timeframe", ["5m", "15m", "1h", "4h"], index=2)

    col_d, col_e = st.columns(2)
    with col_d:
        candle_count = st.slider("Candles Count", min_value=100, max_value=2000, value=500, step=100)
    with col_e:
        initial_cap = st.number_input("Starting Capital ($)", value=10000.0, step=1000.0)

    if st.button("🚀 Run Backtest Simulation", use_container_width=True):
        fetcher = UnifiedDataFetcher()
        backtester = Backtester(initial_balance=initial_cap)

        with st.spinner("Executing simulation..."):
            if asset_type == "FOREX":
                df_hist = fetcher.fetch_forex_candles(symbol, timeframe=tf, count=candle_count)
            else:
                async def fetch_c():
                    res = await fetcher.fetch_crypto_candles(symbol, timeframe=tf, count=candle_count)
                    await fetcher.close()
                    return res
                df_hist = asyncio.run(fetch_c())

            summary, trades_df = backtester.run(df_hist)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Final Balance", f"${summary['final_balance']:,.2f}")
            m2.metric("Total Return", f"{summary['total_return_pct']:.2f}%")
            m3.metric("Win Rate", f"{summary['win_rate_pct']:.1f}%")
            m4.metric("Profit Factor", f"{summary['profit_factor']:.2f}")

            if not trades_df.empty:
                st.line_chart(trades_df.set_index("exit_time")["balance"], title="Portfolio Growth Curve")
                st.dataframe(trades_df, use_container_width=True)
            else:
                st.info("No executed trades triggered within this backtest slice.")

# Client-side auto-reload every 60 seconds
st.components.v1.html(
    """
    <script>
        setTimeout(function(){
            window.parent.location.reload();
        }, 60000);
    </script>
    """,
    height=0
)