import sqlite3
import os
import anthropic
import pandas as pd
from datetime import datetime

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

def init_db():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, side TEXT, entry REAL, sl REAL, tp REAL, score INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS ghost_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, score INTEGER, reason TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, count INTEGER)')
    conn.commit()
    conn.close()

def calculate_math_score(df):
    """AGGRESSIVE: 50+ Score, 1.5x RVOL"""
    df['ema_20'] = df['close'].rolling(20).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    price = df['close'].iloc[-1]
    ema = df['ema_20'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    
    avg_vol = df['volume'].tail(20).mean()
    rvol = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0
    
    direction = 'SHORT' if price < ema else 'LONG'
    score = 50
    if direction == 'SHORT':
        score += 15
        if rsi > 50: score += 15 
    else:
        score += 15
        if rsi < 50: score += 15
        
    if rsi > 85 or rsi < 15: score -= 40
    return score, direction, rvol

def get_aggressive_targets(df, direction):
    """1.5x ATR Stop Loss | 3.0x ATR Take Profit (1:2 Ratio)"""
    price = df['close'].iloc[-1]
    high_low = df['high'] - df['low']
    atr = high_low.rolling(14).mean().iloc[-1]
    
    if direction == 'LONG':
        sl = price - (atr * 1.5)
        tp = price + (atr * 3.0)
    else:
        sl = price + (atr * 1.5)
        tp = price - (atr * 3.0)
    return sl, tp

def call_claude_ai(symbol, timeframe, score):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key: return score
    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"Analyze {symbol} {timeframe}. Score: {score}. Aggressive? Reply only -20 to +20."
    try:
        response = client.messages.create(model=CLAUDE_MODEL, max_tokens=10, messages=[{"role": "user", "content": prompt}])
        points = int(''.join(filter(lambda x: x.isdigit() or x == '-', response.content[0].text)))
        return score + points
    except: return score

def log_trade(symbol, side, entry, sl, tp, score):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO trades (time, symbol, side, entry, sl, tp, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (now, symbol, side, entry, sl, tp, score))
    c.execute("INSERT OR REPLACE INTO daily_stats (date, count) VALUES (?, COALESCE((SELECT count FROM daily_stats WHERE date=?), 0) + 1)", (now[:10], now[:10]))
    conn.commit()
    conn.close()

def log_ghost_trade(symbol, score, reason):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO ghost_trades (time, symbol, score, reason) VALUES (?, ?, ?, ?)", 
              (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), symbol, score, reason))
    conn.commit()
    conn.close()
