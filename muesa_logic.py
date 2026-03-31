import sqlite3
import os
import anthropic
import pandas as pd

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
    conn.commit()
    conn.close()

def call_claude_ai(symbol, timeframe, score):
    """The High-Performance AI Judge (Haiku 3.5)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return score

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        f"Analyze {symbol} on {timeframe}. Math Score: {score}. "
        "Search for Institutional Traps or Accumulation. "
        "Reply with ONLY a number 0-20 to add to the score."
    )

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        ai_points = int(''.join(filter(str.isdigit, response.content[0].text)))
        return score + ai_points
    except:
        return score

def calculate_math_score(data):
    """Placeholder for your technical indicators logic (RSI, EMAs, etc.)"""
    # This should return a base score out of 80
    return 65 

def calculate_atr(data):
    return data['high'].rolling(14).max().iloc[-1] * 0.01

def get_structural_sl(data, side):
    return data['low'].min() if side == 'LONG' else data['high'].max()

def check_cooldown(symbol):
    # Logic to prevent over-trading after a loss
    return True

def log_ghost_trade(time, symbol, score, reason):
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO ghost_trades (time, symbol, score, reason) VALUES (?, ?, ?, ?)", 
              (time, symbol, score, reason))
    conn.commit()
    conn.close()
