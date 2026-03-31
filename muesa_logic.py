import pandas as pd
import numpy as np
import sqlite3
import time
from datetime import datetime

# --- DATABASE SETUP (Data Warehouse) ---
def init_db():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trade_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, direction TEXT, entry_price REAL, score INTEGER, rvol REAL, pnl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ghost_trades 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, score INTEGER, reason TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cooldowns 
                 (symbol TEXT PRIMARY KEY, cooldown_until REAL)''')
    conn.commit()
    conn.close()

def log_trade(symbol, direction, entry_price, score, rvol, pnl=0.0):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO trade_history (timestamp, symbol, direction, entry_price, score, rvol, pnl) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, direction, entry_price, score, rvol, pnl))
    conn.commit()
    conn.close()

def log_ghost_trade(symbol, score, reason):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO ghost_trades (timestamp, symbol, score, reason) VALUES (?, ?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, score, reason))
    conn.commit()
    conn.close()

def check_cooldown(symbol):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("SELECT cooldown_until FROM cooldowns WHERE symbol=?", (symbol,))
    result = c.fetchone()
    conn.close()
    if result and time.time() < result[0]:
        return True
    return False

def set_cooldown(symbol):
    cooldown_time = time.time() + (24 * 3600) # 24 Hours
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("REPLACE INTO cooldowns (symbol, cooldown_until) VALUES (?, ?)", (symbol, cooldown_time))
    conn.commit()
    conn.close()

# --- MATH & INDICATORS ---
def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean().iloc[-1]

def calculate_rvol(df, period=20):
    if len(df) < period + 1: return 1.0
    avg_vol = df['volume'].shift(1).rolling(period).mean().iloc[-1]
    current_vol = df['volume'].iloc[-1]
    if avg_vol == 0: return 1.0
    return current_vol / avg_vol

def get_structural_sl(df, direction, atr):
    last_3 = df.tail(3)
    if direction == 'long':
        struct_low = last_3['low'].min()
        return struct_low - atr
    else:
        struct_high = last_3['high'].max()
        return struct_high + atr

def calculate_math_score(df):
    """Calculates base 60-point trigger using timeframe data."""
    score = 0
    direction = None
    rvol = calculate_rvol(df)
    
    current_close = df['close'].iloc[-1]
    ema_9 = df['close'].ewm(span=9).mean().iloc[-1]
    ema_21 = df['close'].ewm(span=21).mean().iloc[-1]

    # Trend Logic
    if current_close > ema_21 and ema_9 > ema_21:
        direction = 'long'
        score += 35 
    elif current_close < ema_21 and ema_9 < ema_21:
        direction = 'short'
        score += 35

    # Volume & RSI Points (Simplified for Master Code)
    if rvol >= 2.5: score += 25
    
    return score, direction, rvol

def call_claude_ai(symbol, timeframe, score):
    """Placeholder for AI validation (adds the final 15 points to reach 75+)."""
    return score + 15
