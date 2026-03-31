import sqlite3
import os
import anthropic
import requests
from datetime import datetime, timedelta

# LOCK 1: Updated 2026 Model
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

def init_db():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, 
                  side TEXT, entry REAL, sl REAL, tp REAL, score INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ghost_trades 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, 
                  score INTEGER, reason TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cooldowns 
                 (symbol TEXT PRIMARY KEY, expiry TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats 
                 (date TEXT PRIMARY KEY, count INTEGER)''')
    conn.commit()
    conn.close()

def check_filters(symbol, volume_24h, price, supply):
    """LOCK 3: Volume 50M + Market Cap 75M"""
    if volume_24h < 50000000:
        return False, "Low Volume (<50M)"
    
    market_cap = price * supply
    if market_cap < 75000000:
        return False, "Low Market Cap (<75M)"
        
    # LOCK 4: 5 Trades/Day Limit
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("SELECT count FROM daily_stats WHERE date = ?", (today,))
    row = c.fetchone()
    conn.close()
    if row and row[0] >= 5:
        return False, "Daily Limit (5) Reached"
        
    return True, "Passed"

def calculate_math_score(data):
    """New Bi-Directional Logic"""
    score = 50
    price = data['close'].iloc[-1]
    ema = data['ema_20'].iloc[-1]
    rsi = data['rsi'].iloc[-1]

    # SHORT LOGIC (Price below EMA + Room to fall)
    if price < ema:
        score += 15
        if rsi > 50: score += 10 
    
    # LONG LOGIC (Price above EMA + Room to climb)
    if price > ema:
        score += 15
        if rsi < 50: score += 10

    # Safety: Don't trade if RSI is at extreme ends
    if rsi > 80 or rsi < 20: score -= 40
    return score

def call_claude_ai(symbol, side, score, data_summary):
    """LOCK 2: Multi-Timeframe Pattern Recognition"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key: return score
    
    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        f"Analyze {symbol} for a {side} trade. Math Score: {score}. "
        f"Market Data: {data_summary}. "
        "MANDATORY: Check 15m, 1h, 4h trends. "
        "Pattern Hunt: Bull Flag/V-Shape (Long) or Bear Flag/Head & Shoulders (Short). "
        "Reply ONLY with a number -20 to +20."
    )
    try:
        response = client.messages.create(model=CLAUDE_MODEL, max_tokens=10, 
                                          messages=[{"role": "user", "content": prompt}])
        ai_points = int(''.join(filter(lambda x: x.isdigit() or x == '-', response.content[0].text)))
        return score + ai_points
    except: return score

def set_cooldown(symbol):
    """LOCK 5: 24hr SL Cooldown"""
    expiry = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cooldowns (symbol, expiry) VALUES (?, ?)", (symbol, expiry))
    conn.commit()
    conn.close()

def log_trade(time, symbol, side, entry, sl, tp, score):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("INSERT INTO trades (time, symbol, side, entry, sl, tp, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (time, symbol, side, entry, sl, tp, score))
    c.execute("INSERT OR REPLACE INTO daily_stats (date, count) VALUES (?, COALESCE((SELECT count FROM daily_stats WHERE date=?), 0) + 1)", (today, today))
    conn.commit()
    conn.close()
