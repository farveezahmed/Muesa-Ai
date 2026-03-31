import sqlite3
import os
import anthropic
import pandas as pd
from datetime import datetime, timedelta

def init_db():
    """Creates the database tables if they don't exist."""
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    # Live Trades Table
    c.execute('''CREATE TABLE IF NOT EXISTS trades 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, 
                  side TEXT, entry REAL, sl REAL, tp REAL, score INTEGER)''')
    # Ghost Trades Table
    c.execute('''CREATE TABLE IF NOT EXISTS ghost_trades 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, 
                  score INTEGER, reason TEXT)''')
    # Cooldown Table
    c.execute('''CREATE TABLE IF NOT EXISTS cooldowns 
                 (symbol TEXT PRIMARY KEY, expiry TEXT)''')
    conn.commit()
    conn.close()

def log_trade(time, symbol, side, entry, sl, tp, score):
    """Saves a successful trade to the Dashboard database."""
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO trades (time, symbol, side, entry, sl, tp, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (time, symbol, side, entry, sl, tp, score))
    conn.commit()
    conn.close()

def log_ghost_trade(time, symbol, score, reason):
    """Saves a rejected trade (Ghost Trade) to the Dashboard."""
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO ghost_trades (time, symbol, score, reason) VALUES (?, ?, ?, ?)", 
              (time, symbol, score, reason))
    conn.commit()
    conn.close()

def set_cooldown(symbol):
    """The Bodyguard: Activates 24h block after a Stop Loss hit."""
    expiry = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cooldowns (symbol, expiry) VALUES (?, ?)", (symbol, expiry))
    conn.commit()
    conn.close()

def check_cooldown(symbol):
    """Checks if the 24h block is still active."""
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("SELECT expiry FROM cooldowns WHERE symbol = ?", (symbol,))
    row = c.fetchone()
    conn.close()
    if row:
        expiry = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        if datetime.now() < expiry:
            return False # Still cooling down
    return True # Clear to trade

def call_claude_ai(symbol, timeframe, score):
    """The High-Performance AI Judge (Haiku 3.5)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key: return score
    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"Analyze {symbol} on {timeframe}. Math Score: {score}. Looking for institutional traps. Reply with ONLY a number 0-20."
    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        ai_points = int(''.join(filter(str.isdigit, response.content[0].text)))
        return score + ai_points
    except: return score

# Placeholder math functions to prevent errors
def calculate_math_score(data): return 65 
def calculate_atr(data): return data['high'].rolling(14).max().iloc[-1] * 0.01
def get_structural_sl(data, side): return data['low'].min() if side == 'LONG' else data['high'].max()
