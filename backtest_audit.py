
import numpy as np
import pandas as pd
import yfinance as yf

PAIRS = {
    # Forex
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    # Crypto
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD"
}

def fetch_data(ticker, interval="15m", period="60d"):
    """Fetches historical OHLCV data from Yahoo Finance."""
    df = yf.download(ticker, interval=interval, period=period, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
    })
    return df[["open", "high", "low", "close"]].dropna()

def apply_indicators(df):
    """Computes technical indicators identical to our live scanner."""
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

    # RSI 14
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14, min_periods=14).mean()
    avg_loss = loss.rolling(window=14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR 14
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=14, min_periods=14).mean()

    return df.dropna()

def simulate_pair(symbol, ticker):
    """Simulates multi-tier partial exits on historical candles."""
    df = fetch_data(ticker, interval="15m", period="60d")
    if df.empty or len(df) < 250:
        return None

    df = apply_indicators(df)
    
    trades = []
    in_trade = False
    trade = {}

    for i in range(1, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i-1]

        if not in_trade:
            # Check Long Setup
            if curr["close"] > curr["ema200"] and curr["ema20"] > curr["ema50"] and (48 <= curr["rsi"] <= 64) and curr["close"] > prev["close"]:
                in_trade = True
                entry = curr["close"]
                atr = curr["atr"]
                trade = {
                    "direction": "LONG",
                    "entry": entry,
                    "sl": entry - (1.5 * atr),
                    "tp1": entry + (1.0 * atr),
                    "tp2": entry + (1.8 * atr),
                    "tp3": entry + (2.6 * atr),
                    "tp1_hit": False,
                    "tp2_hit": False,
                    "tp3_hit": False,
                    "outcome": "PENDING"
                }

            # Check Short Setup
            elif curr["close"] < curr["ema200"] and curr["ema20"] < curr["ema50"] and (36 <= curr["rsi"] <= 52) and curr["close"] < prev["close"]:
                in_trade = True
                entry = curr["close"]
                atr = curr["atr"]
                trade = {
                    "direction": "SHORT",
                    "entry": entry,
                    "sl": entry + (1.5 * atr),
                    "tp1": entry - (1.0 * atr),
                    "tp2": entry - (1.8 * atr),
                    "tp3": entry - (2.6 * atr),
                    "tp1_hit": False,
                    "tp2_hit": False,
                    "tp3_hit": False,
                    "outcome": "PENDING"
                }

        else:
            # Manage active trade
            if trade["direction"] == "LONG":
                # Check TP targets
                if curr["high"] >= trade["tp1"]:
                    trade["tp1_hit"] = True
                    trade["sl"] = trade["entry"] # Move to Breakeven
                if curr["high"] >= trade["tp2"]:
                    trade["tp2_hit"] = True
                if curr["high"] >= trade["tp3"]:
                    trade["tp3_hit"] = True
                    trade["outcome"] = "TP3_FULL_WIN"
                    trades.append(trade)
                    in_trade = False
                    continue

                # Check Stop Loss
                if curr["low"] <= trade["sl"]:
                    trade["outcome"] = "TP1_BREAKEVEN" if trade["tp1_hit"] else "FULL_LOSS"
                    trades.append(trade)
                    in_trade = False
                    continue

            elif trade["direction"] == "SHORT":
                if curr["low"] <= trade["tp1"]:
                    trade["tp1_hit"] = True
                    trade["sl"] = trade["entry"] # Move to Breakeven
                if curr["low"] <= trade["tp2"]:
                    trade["tp2_hit"] = True
                if curr["low"] <= trade["tp3"]:
                    trade["tp3_hit"] = True
                    trade["outcome"] = "TP3_FULL_WIN"
                    trades.append(trade)
                    in_trade = False
                    continue

                if curr["high"] >= trade["sl"]:
                    trade["outcome"] = "TP1_BREAKEVEN" if trade["tp1_hit"] else "FULL_LOSS"
                    trades.append(trade)
                    in_trade = False
                    continue

    return trades

def run_audit():
    print("=" * 65)
    print("  INSTITUTIONAL STRATEGY AUDIT (PAST 60 DAYS)")
    print("=" * 65)

    all_trades = []
    
    for sym, ticker in PAIRS.items():
        print(f"Auditing {sym}...")
        trades = simulate_pair(sym, ticker)
        if trades:
            for t in trades:
                t["symbol"] = sym
            all_trades.extend(trades)

    if not all_trades:
        print("No trades found in test window.")
        return

    total = len(all_trades)
    tp1_count = sum(1 for t in all_trades if t["tp1_hit"])
    tp2_count = sum(1 for t in all_trades if t["tp2_hit"])
    tp3_count = sum(1 for t in all_trades if t["tp3_hit"])
    full_losses = sum(1 for t in all_trades if t["outcome"] == "FULL_LOSS")
    breakeven_wins = sum(1 for t in all_trades if t["outcome"] == "TP1_BREAKEVEN")

    win_rate = (tp1_count / total) * 100

    print("\n" + "=" * 65)
    print("                FINAL VERIFICATION REPORT")
    print("=" * 65)
    print(f"• Total Signals Generated:    {total}")
    print(f"• Signals Hitting TP1+:       {tp1_count} ({win_rate:.1f}%) -> [Secures Profit + BE]")
    print(f"• Signals Hitting TP2+:       {tp2_count} ({(tp2_count/total)*100:.1f}%)")
    print(f"• Signals Hitting Full TP3:   {tp3_count} ({(tp3_count/total)*100:.1f}%)")
    print(f"• Full Stop-Outs (Losses):    {full_losses} ({(full_losses/total)*100:.1f}%)")
    print(f"• TP1 Breakeven Exits:        {breakeven_wins} ({(breakeven_wins/total)*100:.1f}%)")
    print("=" * 65)

if __name__ == "__main__":
    run_audit()