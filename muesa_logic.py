import sqlite3
import os
import anthropic
import pandas as pd
from datetime import datetime, timedelta

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

def init_db():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, side TEXT, entry REAL, sl REAL, tp REAL, score INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS ghost_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, score INTEGER, reason TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS cooldowns (symbol TEXT PRIMARY KEY, expiry TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, count INTEGER)')
    conn.commit()
    conn.close()

def calculate_math_score(df):
    """Matches Async Scanner: Returns (score, direction, rvol)"""
    df['ema_20'] = df['close'].rolling(20).mean()
    # Simple RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    price = df['close'].iloc[-1]
    ema = df['ema_20'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    
    # RVOL Calculation
    avg_vol = df['volume'].tail(20).mean()
    rvol = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0
    
    direction = 'SHORT' if price < ema else 'LONG'
    score = 50
    if direction == 'SHORT':
        score += 15
        if rsi > 55: score += 10
    else:
        score += 15
        if rsi < 45: score += 10
        
    if rsi > 80 or rsi < 20: score -= 40
    return score, direction, rvol

def call_claude_ai(symbol, timeframe, score):
    """Flexible AI call for MTF and 15m checks"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key: return score
    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"Analyze {symbol} on {timeframe}. Score: {score}. Is this a high-prob pattern? Reply only number -20 to +20."
    try:
        response = client.messages.create(model=CLAUDE_MODEL, max_tokens=10, messages=[{"role": "user", "content": prompt}])
        points = int(''.join(filter(lambda x: x.isdigit() or x == '-', response.content[0].text)))
        return score + points
    except: return score

def calculate_atr(df):
    return (df['high'] - df['low']).rolling(14).mean().iloc[-1]

def get_structural_sl(df, direction, atr):
    price = df['close'].iloc[-1]
    return price + (atr * 2) if direction == 'SHORT' else price - (atr * 2)

def check_cooldown(symbol):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("SELECT expiry FROM cooldowns WHERE symbol=?", (symbol,))
    row = c.fetchone()
    conn.close()
    if row and datetime.now() < datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S'): return True
    return False

def log_ghost_trade(symbol, score, reason):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO ghost_trades (time, symbol, score, reason) VALUES (?, ?, ?, ?)", 
              (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), symbol, score, reason))
    conn.commit()
    conn.close()
