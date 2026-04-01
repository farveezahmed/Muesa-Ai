import os
import sqlite3
import anthropic
import pandas as pd
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MIN_VOLUME_USDT = 50_000_000
MAX_TRADES_PER_DAY = 5

# ─── STATE ────────────────────────────────────────────────────────────────────
trade_count_today = 0
trade_date = ""
cooldown_list = {}

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                time TEXT, symbol TEXT, side TEXT, 
                entry REAL, sl REAL, tp1 REAL, tp2 REAL, score INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ghost_trades 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                time TEXT, symbol TEXT, score INTEGER, reason TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats 
                (date TEXT PRIMARY KEY, count INTEGER)''')
    conn.commit()
    conn.close()

# ─── TRADE COUNT ──────────────────────────────────────────────────────────────
def can_take_trade():
    global trade_count_today, trade_date
    today = datetime.utcnow().date().isoformat()
    if trade_date != today:
        trade_count_today = 0
        trade_date = today
    return trade_count_today < MAX_TRADES_PER_DAY

def increment_trade_count():
    global trade_count_today
    trade_count_today += 1

# ─── COOLDOWN ─────────────────────────────────────────────────────────────────
def set_cooldown(symbol):
    cooldown_list[symbol] = datetime.utcnow()
    print(f"⏳ 24hr cooldown set for {symbol}")

def is_on_cooldown(symbol):
    if symbol in cooldown_list:
        elapsed = datetime.utcnow() - cooldown_list[symbol]
        if elapsed < timedelta(hours=24):
            return True
        else:
            del cooldown_list[symbol]
    return False

# ─── VOLUME FILTER ────────────────────────────────────────────────────────────
def passes_volume_filter(volume_usdt):
    return float(volume_usdt) >= MIN_VOLUME_USDT

# ─── PATTERN 14 — FALSE RECOVERY BLOCK ───────────────────────────────────────
def is_false_recovery(df):
    try:
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        recent_high = max(closes[-20:])
        recent_low = min(closes[-20:])
        recent_drop = (recent_high - recent_low) / recent_high
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        ema99 = df['close'].ewm(span=99).mean().iloc[-1]
        if recent_drop > 0.15 and ema7 < ema25 < ema99:
            return True
    except:
        pass
    return False

# ─── PATTERN: BULL FLAG (LONG) ────────────────────────────────────────────────
def detect_bull_flag(df):
    """
    Bull Flag: strong 10%+ rally over last 30 candles, followed by at least
    10 candles of tight consolidation, then a breakout above the consolidation
    high on 1.5x+ volume. EMA7 > EMA25 and price above both required.
    Returns True if pattern is detected.
    """
    try:
        if len(df) < 40:
            return False

        closes = df['close'].tolist()
        volumes = df['volume'].tolist()

        # Pole: 10%+ rally in the 30 candles before the last 10
        pole_window = closes[-40:-10]
        pole_low = min(pole_window)
        pole_high = max(pole_window)
        if pole_low <= 0:
            return False
        pole_gain = (pole_high - pole_low) / pole_low
        if pole_gain < 0.10:
            return False

        # Consolidation: last 10 candles form a tight range (< 5% spread)
        consol_closes = closes[-10:]
        consol_high = max(consol_closes)
        consol_low = min(consol_closes)
        if consol_low <= 0:
            return False
        consol_range = (consol_high - consol_low) / consol_low
        if consol_range >= 0.05:
            return False

        # Breakout: current close above consolidation high
        current_close = closes[-1]
        if current_close <= consol_high:
            return False

        # Volume spike on breakout candle (1.5x average of prior 20 candles)
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
        if avg_vol <= 0 or volumes[-1] < avg_vol * 1.5:
            return False

        # EMA alignment: EMA7 > EMA25, price above both
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if not (ema7 > ema25 and current_close > ema7 and current_close > ema25):
            return False

        return True
    except:
        pass
    return False

# ─── PATTERN: DEATH CROSS (SHORT) ────────────────────────────────────────────
def detect_death_cross(df):
    """
    Death Cross: EMA7 crosses below EMA25 within the last 5 candles,
    EMA25 is below EMA99 (bearish macro structure), RSI > 60 (overbought
    into the cross), and volume is increasing on the down move.
    Returns True if pattern is detected.
    """
    try:
        if len(df) < 105:
            return False

        ema7_series = df['close'].ewm(span=7).mean()
        ema25_series = df['close'].ewm(span=25).mean()
        ema99_series = df['close'].ewm(span=99).mean()

        # EMA7 must currently be below EMA25
        if ema7_series.iloc[-1] >= ema25_series.iloc[-1]:
            return False

        # Cross must have occurred within the last 5 candles
        crossed = False
        for i in range(2, 7):
            if ema7_series.iloc[-i] >= ema25_series.iloc[-i]:
                crossed = True
                break
        if not crossed:
            return False

        # Bearish macro: EMA25 below EMA99
        if ema25_series.iloc[-1] >= ema99_series.iloc[-1]:
            return False

        # RSI overbought at the cross (> 60)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        if rsi_series.iloc[-1] <= 60:
            return False

        # Volume increasing on down move: last candle volume > prior 3-candle average
        avg_vol_prior = df['volume'].iloc[-4:-1].mean()
        if avg_vol_prior <= 0 or df['volume'].iloc[-1] <= avg_vol_prior:
            return False

        return True
    except:
        pass
    return False

# ─── PATTERN: VOLUME BREAKOUT (LONG) ─────────────────────────────────────────
def detect_volume_breakout(df):
    """
    Volume Breakout: price consolidates in a low-volatility range for 10+
    candles (< 4% spread), then breaks above the consolidation high on a
    2x+ volume spike. EMA7 > EMA25 and RSI < 70 (not yet overbought).
    Returns True if pattern is detected.
    """
    try:
        if len(df) < 15:
            return False

        closes = df['close'].tolist()
        volumes = df['volume'].tolist()

        # Consolidation zone: candles [-11:-1] (10 candles before the current)
        consol_closes = closes[-11:-1]
        consol_high = max(consol_closes)
        consol_low = min(consol_closes)
        if consol_low <= 0:
            return False
        consol_range = (consol_high - consol_low) / consol_low
        if consol_range >= 0.04:
            return False

        # Breakout: current close above consolidation high
        current_close = closes[-1]
        if current_close <= consol_high:
            return False

        # Volume spike: current candle volume >= 2x average of consolidation candles
        avg_consol_vol = sum(volumes[-11:-1]) / 10
        if avg_consol_vol <= 0 or volumes[-1] < avg_consol_vol * 2.0:
            return False

        # EMA alignment: EMA7 > EMA25
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if ema7 <= ema25:
            return False

        # RSI not overbought (< 70)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        if rsi_series.iloc[-1] >= 70:
            return False

        return True
    except:
        pass
    return False

# ─── ATR BASED SL/TP ──────────────────────────────────────────────────────────
def get_sl_tp(df, direction, entry_price):
    high_low = df['high'] - df['low']
    atr = high_low.rolling(14).mean().iloc[-1]
    if direction == 'LONG':
        sl  = entry_price - (atr * 1.5)
        tp1 = entry_price + (atr * 2.0)  # fixed — closes 50% of position
        tp2 = entry_price + (atr * 3.0)  # trailing — closes remaining 50%
    else:
        sl  = entry_price + (atr * 1.5)
        tp1 = entry_price - (atr * 2.0)  # fixed — closes 50% of position
        tp2 = entry_price - (atr * 3.0)  # trailing — closes remaining 50%
    return round(sl, 6), round(tp1, 6), round(tp2, 6)

# ─── MATH SCORE ───────────────────────────────────────────────────────────────
def calculate_math_score(df):
    # EMA
    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_7'] = df['close'].ewm(span=7).mean()
    df['ema_25'] = df['close'].ewm(span=25).mean()

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    price = df['close'].iloc[-1]
    ema7 = df['ema_7'].iloc[-1]
    ema25 = df['ema_25'].iloc[-1]
    rsi = df['rsi'].iloc[-1]

    # Volume
    avg_vol = df['volume'].tail(20).mean()
    rvol = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

    # Direction
    direction = 'LONG' if ema7 > ema25 else 'SHORT'

    # Score starts at 30
    score = 30

    # EMA alignment
    if direction == 'LONG' and ema7 > ema25:
        score += 15
    elif direction == 'SHORT' and ema7 < ema25:
        score += 15

    # RSI
    if direction == 'LONG' and 30 < rsi < 60:
        score += 15
    elif direction == 'SHORT' and 40 < rsi < 70:
        score += 15

    # RVOL
    if rvol >= 1.5:
        score += 15
    elif rvol >= 1.2:
        score += 8

    # RSI extreme penalty
    if rsi > 85 or rsi < 15:
        score -= 40

    # Pattern 14 penalty
    if is_false_recovery(df):
        score -= 30
        print(f"⚠️ Pattern 14 detected — False Recovery penalty applied")

    # Bull Flag bonus (+20, LONG)
    bull_flag = detect_bull_flag(df)
    if bull_flag:
        score += 20
        print(f"🚩 Bull Flag detected — +20 bonus applied (LONG setup)")
    else:
        print(f"🚩 Bull Flag: not detected")

    # Death Cross bonus (+20, SHORT)
    death_cross = detect_death_cross(df)
    if death_cross:
        score += 20
        print(f"💀 Death Cross detected — +20 bonus applied (SHORT setup)")
    else:
        print(f"💀 Death Cross: not detected")

    # Volume Breakout bonus (+15, LONG)
    vol_breakout = detect_volume_breakout(df)
    if vol_breakout:
        score += 15
        print(f"📈 Volume Breakout detected — +15 bonus applied (LONG setup)")
    else:
        print(f"📈 Volume Breakout: not detected")

    return score, direction, rvol, rsi

# ─── CLAUDE API ───────────────────────────────────────────────────────────────
def call_claude_ai(symbol, score, direction, rsi, rvol):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("No Anthropic API key found")
        return score
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are MUESA crypto analyst. Analyze this signal:
Symbol: {symbol}
Direction: {direction}
Math Score: {score}/100
RSI: {rsi:.2f}
RVOL: {rvol:.2f}

Check if this matches any of these patterns:
1. Overnight Dump Recovery
2. Bull Flag
3. Wyckoff Spring

Reply ONLY with a number between -20 and +20 as score adjustment.
Positive if pattern confirmed, negative if pattern invalid."""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        points = int(''.join(c for c in text if c.isdigit() or c == '-'))
        print(f"🤖 Claude adjustment for {symbol}: {points}")
        return score + points
    except Exception as e:
        print(f"Claude error: {e}")
        return score

# ─── LOGGING ──────────────────────────────────────────────────────────────────
def log_trade(symbol, side, entry, sl, tp1, tp2, score):
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO trades (time, symbol, side, entry, sl, tp1, tp2, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (now, symbol, side, entry, sl, tp1, tp2, score))
        c.execute("INSERT OR REPLACE INTO daily_stats (date, count) VALUES (?, COALESCE((SELECT count FROM daily_stats WHERE date=?), 0) + 1)",
                  (now[:10], now[:10]))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Log trade error: {e}")

def log_ghost_trade(symbol, score, reason):
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO ghost_trades (time, symbol, score, reason) VALUES (?, ?, ?, ?)",
                  (datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), symbol, score, reason))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Log ghost error: {e}")
