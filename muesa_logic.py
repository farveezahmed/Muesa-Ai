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
                trend TEXT, dynamic_sl REAL, entry_time TEXT,
                entry_reasons TEXT)''')
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

# ─── FIBONACCI RETRACEMENT ────────────────────────────────────────────────────
def get_fibonacci_levels(df):
    """
    Calculate Fibonacci retracement levels from recent swing high/low.
    Uses last 50 candles to find swing high and swing low.
    Returns dict of fib levels and whether price is near key levels.
    """
    try:
        window = df.tail(50)
        swing_high = window['high'].max()
        swing_low  = window['low'].min()
        diff = swing_high - swing_low

        if diff <= 0:
            return None

        fib_levels = {
            '0.236': swing_high - diff * 0.236,
            '0.382': swing_high - diff * 0.382,
            '0.500': swing_high - diff * 0.500,
            '0.618': swing_high - diff * 0.618,
            '0.786': swing_high - diff * 0.786,
        }

        current_price = df['close'].iloc[-1]

        # Check if price is near key fib levels (within 1.5%)
        near_fib = None
        for level_name, level_price in fib_levels.items():
            if abs(current_price - level_price) / current_price <= 0.015:
                near_fib = level_name
                break

        return {
            'levels': fib_levels,
            'swing_high': swing_high,
            'swing_low': swing_low,
            'near_fib': near_fib,
            'current_price': current_price
        }
    except Exception as e:
        print(f"Fibonacci error: {e}")
        return None

# ─── BOTTOM BOUNCE DETECTION ──────────────────────────────────────────────────
def detect_bottom_bounce(df):
    """
    Detects NOM-type bottom bounce:
    1. Price dropped 20%+ in last 48 candles (48 x 15min = 12 hours)
    2. RSI was below 30 recently (oversold)
    3. Now showing recovery — current price above recent low
    4. Volume spike on bounce candle
    5. EMA7 starting to turn up
    Returns (detected: bool, signals: list)
    """
    try:
        if len(df) < 50:
            return False, []

        closes  = df['close'].tolist()
        volumes = df['volume'].tolist()

        current_price = closes[-1]

        # 1. Big prior dump — 20%+ drop in last 48 candles
        high_48 = max(closes[-48:])
        low_48  = min(closes[-48:])
        if high_48 <= 0:
            return False, []
        dump_pct = (high_48 - low_48) / high_48 * 100

        if dump_pct < 20:
            return False, []

        # 2. RSI was oversold recently (below 30 in last 10 candles)
        delta = df['close'].diff()
        gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = (100 - (100 / (1 + gain / (loss + 1e-9)))).tolist()
        recent_rsi_min = min(rsi_series[-10:])
        was_oversold = recent_rsi_min < 30

        if not was_oversold:
            return False, []

        # 3. Price bouncing — current price above recent low by at least 3%
        recent_low = min(closes[-10:])
        if recent_low <= 0:
            return False, []
        bounce_pct = (current_price - recent_low) / recent_low * 100
        is_bouncing = bounce_pct >= 3

        if not is_bouncing:
            return False, []

        # 4. Volume spike on recent candles
        avg_vol = sum(volumes[-20:-3]) / 17 if len(volumes) >= 20 else 1
        recent_max_vol = max(volumes[-3:])
        volume_spike = recent_max_vol >= avg_vol * 1.5

        # 5. EMA7 turning up
        ema7_series = df['close'].ewm(span=7).mean().tolist()
        ema7_turning_up = ema7_series[-1] > ema7_series[-3]

        signals = [f"Dump: {dump_pct:.1f}%", f"Bounce: {bounce_pct:.1f}%"]
        if volume_spike:
            signals.append("Volume spike")
        if ema7_turning_up:
            signals.append("EMA7 turning up")

        detected = is_bouncing and (volume_spike or ema7_turning_up)
        return detected, signals

    except Exception as e:
        print(f"Bottom bounce error: {e}")
        return False, []

# ─── BOLLINGER SQUEEZE DETECTION ──────────────────────────────────────────────
def detect_bollinger_squeeze(df):
    """
    Bollinger Band Squeeze:
    - Bands were tight (low volatility) for 10+ candles
    - Now expanding (volatility increasing)
    - Price breaking above upper band = LONG
    - Price breaking below lower band = SHORT
    Returns (detected: bool, direction: str or None)
    """
    try:
        if len(df) < 30:
            return False, None

        closes = df['close']
        period = 20
        std_mult = 2.0

        ma   = closes.rolling(period).mean()
        std  = closes.rolling(period).std()
        upper = ma + std_mult * std
        lower = ma - std_mult * std
        bandwidth = ((upper - lower) / ma).tolist()

        current_price = closes.iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]

        # Check if bands were squeezed (bandwidth below 0.05 = tight)
        prev_bandwidth = bandwidth[-11:-1]
        was_squeezed = all(b < 0.08 for b in prev_bandwidth if b > 0)

        if not was_squeezed:
            return False, None

        # Check current expansion
        current_bw = bandwidth[-1]
        prev_bw    = bandwidth[-2]
        is_expanding = current_bw > prev_bw * 1.1

        if not is_expanding:
            return False, None

        # Direction based on breakout
        if current_price > current_upper:
            return True, 'LONG'
        elif current_price < current_lower:
            return True, 'SHORT'

        return False, None

    except Exception as e:
        print(f"Bollinger squeeze error: {e}")
        return False, None

# ─── RSI RESET PULLBACK ───────────────────────────────────────────────────────
def detect_rsi_reset_pullback(df):
    """
    RSI Reset Pullback:
    - Uptrend confirmed (EMA7 > EMA25 > EMA99)
    - RSI pulled back to 35-50 range (healthy retracement)
    - Price near EMA7 or EMA25 support
    - Volume decreasing on pullback (weak sellers)
    Returns (detected: bool)
    """
    try:
        if len(df) < 30:
            return False

        closes  = df['close']
        volumes = df['volume'].tolist()

        ema7  = closes.ewm(span=7).mean()
        ema25 = closes.ewm(span=25).mean()
        ema99 = closes.ewm(span=99).mean()

        # Uptrend required
        if not (ema7.iloc[-1] > ema25.iloc[-1] > ema99.iloc[-1]):
            return False

        # RSI in reset zone 35-50
        delta = df['close'].diff()
        gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - (100 / (1 + gain / (loss + 1e-9)))).iloc[-1]

        if not (35 <= rsi <= 50):
            return False

        # Price near EMA7 or EMA25 (within 2%)
        current_price = closes.iloc[-1]
        near_ema7  = abs(current_price - ema7.iloc[-1])  / current_price <= 0.02
        near_ema25 = abs(current_price - ema25.iloc[-1]) / current_price <= 0.02

        if not (near_ema7 or near_ema25):
            return False

        # Volume decreasing on pullback (last 3 candles lower than average)
        avg_vol    = sum(volumes[-10:-3]) / 7 if len(volumes) >= 10 else 1
        recent_vol = sum(volumes[-3:]) / 3
        weak_sellers = recent_vol < avg_vol * 0.8

        return weak_sellers

    except Exception as e:
        print(f"RSI reset error: {e}")
        return False

# ─── PATTERN 14 — FALSE RECOVERY BLOCK ───────────────────────────────────────
def is_false_recovery(df):
    try:
        closes    = df['close'].tolist()
        recent_high = max(closes[-20:])
        recent_low  = min(closes[-20:])
        recent_drop = (recent_high - recent_low) / recent_high
        ema7  = df['close'].ewm(span=7).mean().iloc[-1]
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
        closes  = df['close'].tolist()
        volumes = df['volume'].tolist()
        pole_window = closes[-40:-10]
        pole_low  = min(pole_window)
        pole_high = max(pole_window)
        if pole_low <= 0:
            return False
        if (pole_high - pole_low) / pole_low < 0.10:
            return False
        consol_closes = closes[-10:]
        consol_high = max(consol_closes)
        consol_low  = min(consol_closes)
        if consol_low <= 0:
            return False
        if (consol_high - consol_low) / consol_low >= 0.05:
            return False
        if closes[-1] <= consol_high:
            return False
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
        if avg_vol <= 0 or volumes[-1] < avg_vol * 1.5:
            return False
        ema7  = df['close'].ewm(span=7).mean().iloc[-1]
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
        ema7_series  = df['close'].ewm(span=7).mean()
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
        gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - (100 / (1 + gain / (loss + 1e-9)))).iloc[-1]
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
        closes  = df['close'].tolist()
        volumes = df['volume'].tolist()
        consol_closes = closes[-11:-1]
        consol_high   = max(consol_closes)
        consol_low    = min(consol_closes)
        if consol_low <= 0:
            return False
        if (consol_high - consol_low) / consol_low >= 0.04:
            return False
        if closes[-1] <= consol_high:
            return False
        avg_vol = sum(volumes[-11:-1]) / 10
        if avg_vol <= 0 or volumes[-1] < avg_vol * 2.0:
            return False
        ema7  = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if ema7 <= ema25:
            return False
        delta = df['close'].diff()
        gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - (100 / (1 + gain / (loss + 1e-9)))).iloc[-1]
        if rsi >= 70:
            return False
        return True
    except:
        return False

# ─── ATR BASED SL/TP WITH SANITY CHECK ───────────────────────────────────────
def get_sl_tp(df, direction, entry_price):
    try:
        high_low   = df['high'] - df['low']
        atr_series = high_low.rolling(14).mean()
        current_atr = atr_series.iloc[-1]

        avg_atr_20      = atr_series.iloc[-20:].mean() if len(atr_series) >= 20 else current_atr
        volatility_ratio = current_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0

        if volatility_ratio > 1.5:
            sl_multiplier = 2.0
        elif volatility_ratio < 0.7:
            sl_multiplier = 1.0
        else:
            sl_multiplier = 1.5

        print(f"📐 ATR: {current_atr:.8f} | Vol ratio: {volatility_ratio:.2f} | SL mult: {sl_multiplier}x")

        if direction == 'LONG':
            sl  = entry_price - (current_atr * sl_multiplier)
            tp1 = entry_price + (current_atr * 2.0)
            tp2 = entry_price + (current_atr * 3.0)
        else:
            sl  = entry_price + (current_atr * sl_multiplier)
            tp1 = entry_price - (current_atr * 2.0)
            tp2 = entry_price - (current_atr * 3.0)

    except Exception as e:
        print(f"ATR error: {e} — using fixed %")
        if direction == 'LONG':
            sl  = entry_price * 0.97
            tp1 = entry_price * 1.04
            tp2 = entry_price * 1.06
        else:
            sl  = entry_price * 1.03
            tp1 = entry_price * 0.96
            tp2 = entry_price * 0.94

    # ── SANITY CHECK ──────────────────────────────────────────────────────────
    if direction == 'LONG':
        if sl >= entry_price:
            sl = entry_price * 0.97
            print(f"⚠️ SL sanity fix LONG")
        if tp1 <= entry_price:
            tp1 = entry_price * 1.04
            print(f"⚠️ TP1 sanity fix LONG")
        if tp2 <= tp1:
            tp2 = entry_price * 1.06
            print(f"⚠️ TP2 sanity fix LONG")
        # Minimum 1% SL distance
        if sl > entry_price * 0.99:
            sl = entry_price * 0.99
    else:
        if sl <= entry_price:
            sl = entry_price * 1.03
            print(f"⚠️ SL sanity fix SHORT")
        if tp1 >= entry_price:
            tp1 = entry_price * 0.96
            print(f"⚠️ TP1 sanity fix SHORT")
        if tp2 >= tp1:
            tp2 = entry_price * 0.94
            print(f"⚠️ TP2 sanity fix SHORT")
        # Minimum 1% SL distance
        if sl < entry_price * 1.01:
            sl = entry_price * 1.01

    return round(sl, 8), round(tp1, 8), round(tp2, 8)

# ─── SUPPORT / RESISTANCE ─────────────────────────────────────────────────────
def detect_support_resistance(df):
    try:
        if len(df) < 10:
            return None, None, 0, 0
        window = df.tail(50)
        highs  = window['high'].tolist()
        lows   = window['low'].tolist()
        closes = window['close'].tolist()
        resistance_candidates = []
        support_candidates    = []
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
        print(f"S/R error: {e}")
        return None, None, 0, 0

# ─── RSI DIVERGENCE ───────────────────────────────────────────────────────────
def detect_rsi_divergence(df):
    try:
        if len(df) < 25:
            return None, 0
        delta      = df['close'].diff()
        gain       = delta.where(delta > 0, 0).rolling(14).mean()
        loss       = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = (100 - (100 / (1 + gain / (loss + 1e-9)))).tolist()
        closes     = df['close'].tolist()
        ref_close  = closes[-1]
        ref_rsi    = rsi_series[-1]
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
        ema200   = df_1h['close'].ewm(span=200).mean().iloc[-1]
        price    = df_1h['close'].iloc[-1]
        pct_diff = (price - ema200) / ema200
        if pct_diff > 0.02:
            return "BULLISH"
        elif pct_diff < -0.02:
            return "BEARISH"
        return "NEUTRAL"
    except Exception as e:
        print(f"Trend error: {e}")
        return "NEUTRAL"

# ─── LIQUIDITY ZONE ───────────────────────────────────────────────────────────
def is_in_liquidity_zone(df, support, resistance):
    try:
        current_price = df['close'].iloc[-1]
        volumes       = df['volume'].tolist()
        avg_vol       = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1.0
        high_volume   = volumes[-1] >= avg_vol * 1.5
        in_zone = False
        if support is not None:
            if abs(current_price - support) / support <= 0.015:
                in_zone = True
        if resistance is not None:
            if abs(current_price - resistance) / resistance <= 0.015:
                in_zone = True
        return in_zone, in_zone and high_volume
    except Exception as e:
        print(f"Liquidity zone error: {e}")
        return False, False

# ─── MAIN SCORING ─────────────────────────────────────────────────────────────
def calculate_math_score(df, df_1h=None):
    entry_reasons = []

    df['ema_7']  = df['close'].ewm(span=7).mean()
    df['ema_25'] = df['close'].ewm(span=25).mean()
    df['ema_20'] = df['close'].ewm(span=20).mean()

    delta    = df['close'].diff()
    gain     = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss     = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

    price = df['close'].iloc[-1]
    ema7  = df['ema_7'].iloc[-1]
    ema25 = df['ema_25'].iloc[-1]
    rsi   = df['rsi'].iloc[-1]

    avg_vol = df['volume'].tail(20).mean()
    rvol    = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

    direction = 'LONG' if ema7 > ema25 else 'SHORT'
    score = 30

    # ── Base EMA ──────────────────────────────────────────────────────────────
    if direction == 'LONG' and ema7 > ema25:
        score += 15
        entry_reasons.append("EMA7>EMA25 bullish")
    elif direction == 'SHORT' and ema7 < ema25:
        score += 15
        entry_reasons.append("EMA7<EMA25 bearish")

    # ── RSI ───────────────────────────────────────────────────────────────────
    if direction == 'LONG' and 30 < rsi < 60:
        score += 15
        entry_reasons.append(f"RSI healthy {rsi:.1f}")
    elif direction == 'SHORT' and 40 < rsi < 70:
        score += 15
        entry_reasons.append(f"RSI healthy {rsi:.1f}")

    # ── RSI extreme penalties ─────────────────────────────────────────────────
    if rsi > 85 or rsi < 15:
        score -= 40
        entry_reasons.append(f"⚠️ RSI extreme {rsi:.1f} -40")
    if direction == 'LONG' and rsi > 70:
        score -= 25
        entry_reasons.append(f"⚠️ RSI overbought LONG {rsi:.1f} -25")
    if direction == 'SHORT' and rsi < 30:
        score -= 25
        entry_reasons.append(f"⚠️ RSI oversold SHORT {rsi:.1f} -25")

    # ── RVOL ──────────────────────────────────────────────────────────────────
    if rvol >= 1.5:
        score += 15
        entry_reasons.append(f"RVOL strong {rvol:.2f}")
    elif rvol >= 1.2:
        score += 8
        entry_reasons.append(f"RVOL moderate {rvol:.2f}")
    elif rvol < 0.5:
        score -= 20
        entry_reasons.append(f"⚠️ RVOL weak {rvol:.2f} -20")

    # ── Pattern 14 ────────────────────────────────────────────────────────────
    if is_false_recovery(df):
        score -= 30
        entry_reasons.append("⚠️ Pattern14 false recovery -30")

    # ── Bottom Bounce ─────────────────────────────────────────────────────────
    bb_detected, bb_signals = detect_bottom_bounce(df)
    if bb_detected:
        score += 25
        entry_reasons.append(f"🎯 Bottom bounce: {', '.join(bb_signals)}")
        print(f"🎯 Bottom bounce detected +25: {bb_signals}")

    # ── Bollinger Squeeze ─────────────────────────────────────────────────────
    boll_detected, boll_dir = detect_bollinger_squeeze(df)
    if boll_detected and boll_dir == direction:
        score += 20
        entry_reasons.append(f"📊 Bollinger squeeze breakout {boll_dir}")
        print(f"📊 Bollinger squeeze +20")

    # ── RSI Reset Pullback ────────────────────────────────────────────────────
    if detect_rsi_reset_pullback(df) and direction == 'LONG':
        score += 20
        entry_reasons.append("🔄 RSI reset pullback")
        print(f"🔄 RSI reset pullback +20")

    # ── Bull Flag ─────────────────────────────────────────────────────────────
    if detect_bull_flag(df):
        score += 20
        entry_reasons.append("🚩 Bull flag")
        print(f"🚩 Bull flag +20")

    # ── Death Cross ───────────────────────────────────────────────────────────
    if detect_death_cross(df):
        score += 20
        entry_reasons.append("💀 Death cross")
        print(f"💀 Death cross +20")

    # ── Volume Breakout ───────────────────────────────────────────────────────
    if detect_volume_breakout(df):
        score += 15
        entry_reasons.append("📈 Volume breakout")
        print(f"📈 Volume breakout +15")

    # ── Fibonacci ─────────────────────────────────────────────────────────────
    fib_data = get_fibonacci_levels(df)
    if fib_data and fib_data['near_fib']:
        fib_level = fib_data['near_fib']
        if fib_level in ['0.382', '0.618'] and direction == 'LONG':
            score += 20
            entry_reasons.append(f"🌀 Fib {fib_level} support")
            print(f"🌀 Fibonacci {fib_level} support +20")
        elif fib_level in ['0.236', '0.382'] and direction == 'SHORT':
            score += 15
            entry_reasons.append(f"🌀 Fib {fib_level} resistance")
            print(f"🌀 Fibonacci {fib_level} resistance +15")

    # ── Support / Resistance ──────────────────────────────────────────────────
    support, resistance, sup_strength, res_strength = detect_support_resistance(df)
    print(f"📊 S/R — Support: {support} (×{sup_strength}) | Resistance: {resistance} (×{res_strength})")

    if support is not None and price > 0:
        near_support    = abs(price - support) / price <= 0.02
        near_resistance = resistance is not None and abs(price - resistance) / price <= 0.02
        if near_support or near_resistance:
            score -= 10
            entry_reasons.append("⚠️ Near S/R -10")
        if resistance is not None and price > resistance and rvol >= 1.5:
            score += 15
            entry_reasons.append("🚀 Liquidity breakout +15")
            print(f"🚀 Liquidity breakout +15")

    # ── RSI Divergence ────────────────────────────────────────────────────────
    divergence_type, candles_back = detect_rsi_divergence(df)
    if divergence_type:
        print(f"🔀 Divergence: {divergence_type} ({candles_back} candles back)")
        if candles_back <= 5:
            if divergence_type == "BULLISH" and direction == "LONG":
                score += 20
                entry_reasons.append(f"🔀 Bullish divergence")
                print(f"✅ Bullish divergence +20")
            elif divergence_type == "BEARISH" and direction == "SHORT":
                score += 20
                entry_reasons.append(f"🔀 Bearish divergence")
                print(f"✅ Bearish divergence +20")
    else:
        divergence_type = None

    # ── Trend Filter ──────────────────────────────────────────────────────────
    trend = get_trend_filter(df_1h)
    print(f"📈 Trend: {trend}")
    if direction == "LONG":
        if trend == "BEARISH":
            score -= 30
            entry_reasons.append("⛔ Counter-trend LONG -30")
            print(f"⛔ Counter-trend LONG -30")
        elif trend == "BULLISH":
            score += 10
            entry_reasons.append("✅ Trend aligned bullish")
            print(f"✅ Trend aligned +10")
    elif direction == "SHORT":
        if trend == "BULLISH":
            score -= 30
            entry_reasons.append("⛔ Counter-trend SHORT -30")
            print(f"⛔ Counter-trend SHORT -30")
        elif trend == "BEARISH":
            score += 10
            entry_reasons.append("✅ Trend aligned bearish")
            print(f"✅ Trend aligned +10")

    # ── Liquidity Zone ────────────────────────────────────────────────────────
    in_zone, liq_breakout = is_in_liquidity_zone(df, support, resistance)
    if liq_breakout:
        score += 15
        entry_reasons.append("💧 Liquidity breakout")
        print(f"💧 Liquidity breakout +15")
    elif in_zone:
        score -= 15
        entry_reasons.append("⚠️ Inside liquidity zone -15")
        print(f"⚠️ Inside liquidity zone -15")

    # ── CAP SCORE AT 100 ──────────────────────────────────────────────────────
    score = min(score, 100)
    score = max(score, 0)

    return score, direction, rvol, rsi, support, resistance, divergence_type, trend, entry_reasons

# ─── CLAUDE API ───────────────────────────────────────────────────────────────
def call_claude_ai(symbol, score, direction, rsi, rvol, entry_reasons):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("No Anthropic API key")
        return score
    try:
        client = anthropic.Anthropic(api_key=api_key)
        reasons_text = ', '.join(entry_reasons[:5]) if entry_reasons else 'None'
        prompt = f"""You are MUESA crypto analyst. Analyze this signal:
Symbol: {symbol}
Direction: {direction}
Math Score: {score}/100
RSI: {rsi:.2f}
RVOL: {rvol:.2f}
Key signals: {reasons_text}

Check if this matches any of these patterns:
1. Overnight Dump Recovery
2. Bull Flag
3. Wyckoff Spring
4. Bottom Bounce

Reply ONLY with a single integer between -20 and +20.
No text, no symbols, just the number. Example: 15"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        text    = response.content[0].text.strip()
        cleaned = ''.join(c for c in text if c.isdigit() or c == '-').strip()
        if not cleaned or cleaned == '-':
            return score
        points = max(-20, min(20, int(cleaned)))
        print(f"🤖 Claude adjustment: {points}")
        return score + points
    except Exception as e:
        print(f"Claude error: {e}")
        return score

# ─── LOGGING ──────────────────────────────────────────────────────────────────
def log_trade(symbol, side, entry, sl, tp1, tp2, score,
              support=None, resistance=None, divergence=None,
              trend=None, dynamic_sl=None, entry_reasons=None):
    try:
        conn = sqlite3.connect('muesa_data.db')
        c    = conn.cursor()
        now  = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        reasons_str = ' | '.join(entry_reasons) if entry_reasons else ''
        c.execute(
            """INSERT INTO trades
               (time, symbol, side, entry, sl, tp1, tp2, score,
                support, resistance, divergence, trend, dynamic_sl,
                entry_time, entry_reasons)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, symbol, side, entry, sl, tp1, tp2, score,
             support, resistance, divergence, trend, dynamic_sl, now, reasons_str)
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
        c    = conn.cursor()
        c.execute(
            "INSERT INTO ghost_trades (time, symbol, score, reason) VALUES (?, ?, ?, ?)",
            (datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), symbol, score, reason)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Log ghost error: {e}")
