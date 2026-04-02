import os
import sqlite3
import anthropic
import pandas as pd
import numpy as np
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
                entry REAL, sl REAL, tp1 REAL, tp2 REAL, score INTEGER,
                support REAL, resistance REAL, divergence TEXT,
                trend TEXT, dynamic_sl REAL, entry_time TEXT)''')
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

# ─── PATTERN: BULL FLAG ───────────────────────────────────────────────────────
def detect_bull_flag(df):
    try:
        if len(df) < 40:
            return False
        closes = df['close'].tolist()
        volumes = df['volume'].tolist()
        pole_window = closes[-40:-10]
        pole_low = min(pole_window)
        pole_high = max(pole_window)
        if pole_low <= 0:
            return False
        if (pole_high - pole_low) / pole_low < 0.10:
            return False
        consol_closes = closes[-10:]
        consol_high = max(consol_closes)
        consol_low = min(consol_closes)
        if consol_low <= 0:
            return False
        if (consol_high - consol_low) / consol_low >= 0.05:
            return False
        if closes[-1] <= consol_high:
            return False
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
        if avg_vol <= 0 or volumes[-1] < avg_vol * 1.5:
            return False
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if not (ema7 > ema25 and closes[-1] > ema7):
            return False
        return True
    except:
        return False

# ─── PATTERN: DEATH CROSS ─────────────────────────────────────────────────────
def detect_death_cross(df):
    try:
        if len(df) < 105:
            return False
        ema7_series = df['close'].ewm(span=7).mean()
        ema25_series = df['close'].ewm(span=25).mean()
        ema99_series = df['close'].ewm(span=99).mean()
        if ema7_series.iloc[-1] >= ema25_series.iloc[-1]:
            return False
        crossed = any(
            ema7_series.iloc[-i] >= ema25_series.iloc[-i]
            for i in range(2, 7)
        )
        if not crossed:
            return False
        if ema25_series.iloc[-1] >= ema99_series.iloc[-1]:
            return False
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = (100 - (100 / (1 + gain / (loss + 1e-9)))).iloc[-1]
        if rsi <= 60:
            return False
        avg_vol = df['volume'].iloc[-4:-1].mean()
        if avg_vol <= 0 or df['volume'].iloc[-1] <= avg_vol:
            return False
        return True
    except:
        return False

# ─── PATTERN: VOLUME BREAKOUT ─────────────────────────────────────────────────
def detect_volume_breakout(df):
    try:
        if len(df) < 15:
            return False
        closes = df['close'].tolist()
        volumes = df['volume'].tolist()
        consol_closes = closes[-11:-1]
        consol_high = max(consol_closes)
        consol_low = min(consol_closes)
        if consol_low <= 0:
            return False
        if (consol_high - consol_low) / consol_low >= 0.04:
            return False
        if closes[-1] <= consol_high:
            return False
        avg_vol = sum(volumes[-11:-1]) / 10
        if avg_vol <= 0 or volumes[-1] < avg_vol * 2.0:
            return False
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if ema7 <= ema25:
            return False
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = (100 - (100 / (1 + gain / (loss + 1e-9)))).iloc[-1]
        if rsi >= 70:
            return False
        return True
    except:
        return False

# ─── ATR BASED SL/TP WITH SANITY CHECK ───────────────────────────────────────
def get_sl_tp(df, direction, entry_price):
    try:
        high_low = df['high'] - df['low']
        atr_series = high_low.rolling(14).mean()
        current_atr = atr_series.iloc[-1]

        # Volatility ratio
        avg_atr_20 = atr_series.iloc[-20:].mean() if len(atr_series) >= 20 else current_atr
        volatility_ratio = current_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0

        if volatility_ratio > 1.5:
            sl_multiplier = 2.0
        elif volatility_ratio < 0.7:
            sl_multiplier = 1.0
        else:
            sl_multiplier = 1.5

        print(f"📐 ATR: {current_atr:.6f} | Volatility ratio: {volatility_ratio:.2f} | SL multiplier: {sl_multiplier}x")

        if direction == 'LONG':
            sl  = entry_price - (current_atr * sl_multiplier)
            tp1 = entry_price + (current_atr * 2.0)
            tp2 = entry_price + (current_atr * 3.0)
        else:
            sl  = entry_price + (current_atr * sl_multiplier)
            tp1 = entry_price - (current_atr * 2.0)
            tp2 = entry_price - (current_atr * 3.0)

    except Exception as e:
        print(f"ATR calculation error: {e}")
        # Fallback to fixed percentage
        if direction == 'LONG':
            sl  = entry_price * 0.97
            tp1 = entry_price * 1.04
            tp2 = entry_price * 1.06
        else:
            sl  = entry_price * 1.03
            tp1 = entry_price * 0.96
            tp2 = entry_price * 0.94

    # ── SANITY CHECK — most important fix ─────────────────────────────────────
    if direction == 'LONG':
        if sl >= entry_price:
            print(f"⚠️ SL sanity fix — was {sl}, correcting to 3% below entry")
            sl = entry_price * 0.97
        if tp1 <= entry_price:
            print(f"⚠️ TP1 sanity fix — was {tp1}, correcting to 4% above entry")
            tp1 = entry_price * 1.04
        if tp2 <= tp1:
            print(f"⚠️ TP2 sanity fix — was {tp2}, correcting to 6% above entry")
            tp2 = entry_price * 1.06
    else:
        if sl <= entry_price:
            print(f"⚠️ SL sanity fix — was {sl}, correcting to 3% above entry")
            sl = entry_price * 1.03
        if tp1 >= entry_price:
            print(f"⚠️ TP1 sanity fix — was {tp1}, correcting to 4% below entry")
            tp1 = entry_price * 0.96
        if tp2 >= tp1:
            print(f"⚠️ TP2 sanity fix — was {tp2}, correcting to 6% below entry")
            tp2 = entry_price * 0.94

    return round(sl, 8), round(tp1, 8), round(tp2, 8)

# ─── SUPPORT / RESISTANCE ─────────────────────────────────────────────────────
def detect_support_resistance(df):
    try:
        if len(df) < 10:
            return None, None, 0, 0
        window = df.tail(50)
        closes = window['close'].tolist()
        highs  = window['high'].tolist()
        lows   = window['low'].tolist()
        resistance_candidates = []
        support_candidates = []
        for i in range(1, len(closes) - 1):
            if highs[i] >= highs[i-1] and highs[i] >= highs[i+1]:
                resistance_candidates.append(highs[i])
            if lows[i] <= lows[i-1] and lows[i] <= lows[i+1]:
                support_candidates.append(lows[i])

        def cluster_levels(levels, tolerance=0.01):
            if not levels:
                return []
            levels_sorted = sorted(levels)
            clusters = []
            current_cluster = [levels_sorted[0]]
            for lvl in levels_sorted[1:]:
                if (lvl - current_cluster[0]) / current_cluster[0] <= tolerance:
                    current_cluster.append(lvl)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [lvl]
            clusters.append(current_cluster)
            return [(sum(c) / len(c), len(c)) for c in clusters]

        res_clusters = cluster_levels(resistance_candidates)
        sup_clusters = cluster_levels(support_candidates)
        best_resistance = max(res_clusters, key=lambda x: x[1]) if res_clusters else (None, 0)
        best_support    = max(sup_clusters, key=lambda x: x[1]) if sup_clusters else (None, 0)
        support_level    = round(best_support[0],    8) if best_support[0]    else None
        resistance_level = round(best_resistance[0], 8) if best_resistance[0] else None
        return support_level, resistance_level, best_support[1], best_resistance[1]
    except Exception as e:
        print(f"S/R detection error: {e}")
        return None, None, 0, 0

# ─── RSI DIVERGENCE ───────────────────────────────────────────────────────────
def detect_rsi_divergence(df):
    try:
        if len(df) < 25:
            return None, 0
        delta = df['close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = (100 - (100 / (1 + gain / (loss + 1e-9)))).tolist()
        closes = df['close'].tolist()
        ref_close = closes[-1]
        ref_rsi   = rsi_series[-1]
        for i in range(2, 21):
            past_close = closes[-i]
            past_rsi   = rsi_series[-i]
            if ref_close < past_close and ref_rsi > past_rsi:
                return "BULLISH", i - 1
            if ref_close > past_close and ref_rsi < past_rsi:
                return "BEARISH", i - 1
        return None, 0
    except Exception as e:
        print(f"Divergence error: {e}")
        return None, 0

# ─── TREND FILTER ─────────────────────────────────────────────────────────────
def get_trend_filter(df_1h):
    try:
        if df_1h is None or len(df_1h) < 50:
            return "NEUTRAL"
        ema200 = df_1h['close'].ewm(span=200).mean().iloc[-1]
        price  = df_1h['close'].iloc[-1]
        pct_diff = (price - ema200) / ema200
        if pct_diff > 0.02:
            return "BULLISH"
        elif pct_diff < -0.02:
            return "BEARISH"
        return "NEUTRAL"
    except Exception as e:
        print(f"Trend filter error: {e}")
        return "NEUTRAL"

# ─── LIQUIDITY ZONE ───────────────────────────────────────────────────────────
def is_in_liquidity_zone(df, support, resistance):
    try:
        current_price = df['close'].iloc[-1]
        volumes = df['volume'].tolist()
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1.0
        high_volume = volumes[-1] >= avg_vol * 1.5
        in_zone = False
        if support is not None:
            if abs(current_price - support) / support <= 0.015:
                in_zone = True
        if resistance is not None:
            if abs(current_price - resistance) / resistance <= 0.015:
                in_zone = True
        breakout = in_zone and high_volume
        return in_zone, breakout
    except Exception as e:
        print(f"Liquidity zone error: {e}")
        return False, False

# ─── MATH SCORE ───────────────────────────────────────────────────────────────
def calculate_math_score(df, df_1h=None):
    df['ema_7']  = df['close'].ewm(span=7).mean()
    df['ema_25'] = df['close'].ewm(span=25).mean()
    df['ema_20'] = df['close'].ewm(span=20).mean()

    delta = df['close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

    price = df['close'].iloc[-1]
    ema7  = df['ema_7'].iloc[-1]
    ema25 = df['ema_25'].iloc[-1]
    rsi   = df['rsi'].iloc[-1]

    avg_vol = df['volume'].tail(20).mean()
    rvol    = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

    direction = 'LONG' if ema7 > ema25 else 'SHORT'
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

    # Pattern 14
    if is_false_recovery(df):
        score -= 30
        print(f"⚠️ Pattern 14 — False Recovery penalty")

    # Bull Flag
    if detect_bull_flag(df):
        score += 20
        print(f"🚩 Bull Flag detected +20")

    # Death Cross
    if detect_death_cross(df):
        score += 20
        print(f"💀 Death Cross detected +20")

    # Volume Breakout
    if detect_volume_breakout(df):
        score += 15
        print(f"📈 Volume Breakout detected +15")

    # Support / Resistance
    support, resistance, sup_strength, res_strength = detect_support_resistance(df)
    print(f"📊 S/R — Support: {support} (×{sup_strength}) | Resistance: {resistance} (×{res_strength})")

    if support is not None and price > 0:
        near_support    = abs(price - support) / price <= 0.02
        near_resistance = resistance is not None and abs(price - resistance) / price <= 0.02
        if near_support or near_resistance:
            score -= 10
            print(f"⚠️ Near S/R level -10")
        if resistance is not None and price > resistance and rvol >= 1.5:
            score += 15
            print(f"🚀 Liquidity breakout +15")

    # RSI Divergence
    divergence_type, candles_back = detect_rsi_divergence(df)
    if divergence_type:
        print(f"🔀 Divergence: {divergence_type} ({candles_back} candles back)")
        if candles_back <= 5:
            if divergence_type == "BULLISH" and direction == "LONG":
                score += 20
                print(f"✅ Bullish divergence +20")
            elif divergence_type == "BEARISH" and direction == "SHORT":
                score += 20
                print(f"✅ Bearish divergence +20")
    else:
        divergence_type = None

    # Trend filter
    trend = get_trend_filter(df_1h)
    print(f"📈 Trend: {trend}")
    if direction == "LONG":
        if trend == "BEARISH":
            score -= 30
            print(f"⛔ Counter-trend LONG -30")
        elif trend == "BULLISH":
            score += 10
            print(f"✅ Trend aligned +10")
    elif direction == "SHORT":
        if trend == "BULLISH":
            score -= 30
            print(f"⛔ Counter-trend SHORT -30")
        elif trend == "BEARISH":
            score += 10
            print(f"✅ Trend aligned +10")

    # Liquidity zone
    in_zone, liq_breakout = is_in_liquidity_zone(df, support, resistance)
    if liq_breakout:
        score += 15
        print(f"💧 Liquidity breakout +15")
    elif in_zone:
        score -= 15
        print(f"⚠️ Inside liquidity zone -15")

    return score, direction, rvol, rsi, support, resistance, divergence_type, trend

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
        print(f"🤖 Claude adjustment: {points}")
        return score + points
    except Exception as e:
        print(f"Claude error: {e}")
        return score

# ─── LOGGING ──────────────────────────────────────────────────────────────────
def log_trade(symbol, side, entry, sl, tp1, tp2, score,
              support=None, resistance=None, divergence=None,
              trend=None, dynamic_sl=None):
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            """INSERT INTO trades
               (time, symbol, side, entry, sl, tp1, tp2, score,
                support, resistance, divergence, trend, dynamic_sl, entry_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, symbol, side, entry, sl, tp1, tp2, score,
             support, resistance, divergence, trend, dynamic_sl, now)
        )
        c.execute(
            "INSERT OR REPLACE INTO daily_stats (date, count) "
            "VALUES (?, COALESCE((SELECT count FROM daily_stats WHERE date=?), 0) + 1)",
            (now[:10], now[:10])
        )
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
