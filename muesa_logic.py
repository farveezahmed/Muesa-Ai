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
                confluence_count INTEGER, multi_tf_score INTEGER,
                rr_ratio REAL, vol_regime TEXT)''')
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

    Returns (detected: bool, strength: 1-5)
      Strength 1: Barely meets criteria
      Strength 5: Perfect setup (10%+ rally, <2% consolidation, 2x+ volume)
    """
    try:
        if len(df) < 40:
            return False, 0

        closes = df['close'].tolist()
        volumes = df['volume'].tolist()

        # Pole: 10%+ rally in the 30 candles before the last 10
        pole_window = closes[-40:-10]
        pole_low = min(pole_window)
        pole_high = max(pole_window)
        if pole_low <= 0:
            return False, 0
        pole_gain = (pole_high - pole_low) / pole_low
        if pole_gain < 0.10:
            return False, 0

        # Consolidation: last 10 candles form a tight range (< 5% spread)
        consol_closes = closes[-10:]
        consol_high = max(consol_closes)
        consol_low = min(consol_closes)
        if consol_low <= 0:
            return False, 0
        consol_range = (consol_high - consol_low) / consol_low
        if consol_range >= 0.05:
            return False, 0

        # Breakout: current close above consolidation high
        current_close = closes[-1]
        if current_close <= consol_high:
            return False, 0

        # Volume spike on breakout candle (1.5x average of prior 20 candles)
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
        if avg_vol <= 0 or volumes[-1] < avg_vol * 1.5:
            return False, 0

        # EMA alignment: EMA7 > EMA25, price above both
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if not (ema7 > ema25 and current_close > ema7 and current_close > ema25):
            return False, 0

        # ── Strength scoring (1-5) ────────────────────────────────────────────
        strength = 1
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

        # Pole gain quality
        if pole_gain >= 0.15:
            strength += 1
        # Tight consolidation
        if consol_range < 0.02:
            strength += 1
        # Strong volume spike
        if vol_ratio >= 2.0:
            strength += 1
        # All three premium criteria met simultaneously
        if pole_gain >= 0.10 and consol_range < 0.02 and vol_ratio >= 2.0:
            strength = 5

        strength = min(strength, 5)
        return True, strength
    except:
        pass
    return False, 0

# ─── PATTERN: DEATH CROSS (SHORT) ────────────────────────────────────────────
def detect_death_cross(df):
    """
    Death Cross: EMA7 crosses below EMA25 within the last 5 candles,
    EMA25 is below EMA99 (bearish macro structure), RSI > 60 (overbought
    into the cross), and volume is increasing on the down move.

    Returns (detected: bool, strength: 1-5)
      Strength 1: EMA7 just crossed below EMA25
      Strength 5: Clean cross, RSI 70+, volume spike 2x+
    """
    try:
        if len(df) < 105:
            return False, 0

        ema7_series = df['close'].ewm(span=7).mean()
        ema25_series = df['close'].ewm(span=25).mean()
        ema99_series = df['close'].ewm(span=99).mean()

        # EMA7 must currently be below EMA25
        if ema7_series.iloc[-1] >= ema25_series.iloc[-1]:
            return False, 0

        # Cross must have occurred within the last 5 candles
        crossed = False
        for i in range(2, 7):
            if ema7_series.iloc[-i] >= ema25_series.iloc[-i]:
                crossed = True
                break
        if not crossed:
            return False, 0

        # Bearish macro: EMA25 below EMA99
        if ema25_series.iloc[-1] >= ema99_series.iloc[-1]:
            return False, 0

        # RSI overbought at the cross (> 60)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        rsi_val = rsi_series.iloc[-1]
        if rsi_val <= 60:
            return False, 0

        # Volume increasing on down move: last candle volume > prior 3-candle average
        avg_vol_prior = df['volume'].iloc[-4:-1].mean()
        if avg_vol_prior <= 0 or df['volume'].iloc[-1] <= avg_vol_prior:
            return False, 0

        # ── Strength scoring (1-5) ────────────────────────────────────────────
        strength = 1
        vol_ratio = df['volume'].iloc[-1] / avg_vol_prior if avg_vol_prior > 0 else 1.0

        # RSI deeply overbought
        if rsi_val >= 70:
            strength += 1
        # Strong volume spike
        if vol_ratio >= 2.0:
            strength += 1
        # EMA separation (clean cross): EMA7 clearly below EMA25
        ema_gap = (ema25_series.iloc[-1] - ema7_series.iloc[-1]) / ema25_series.iloc[-1]
        if ema_gap >= 0.005:
            strength += 1
        # All premium criteria met
        if rsi_val >= 70 and vol_ratio >= 2.0 and ema_gap >= 0.005:
            strength = 5

        strength = min(strength, 5)
        return True, strength
    except:
        pass
    return False, 0

# ─── PATTERN: VOLUME BREAKOUT (LONG) ─────────────────────────────────────────
def detect_volume_breakout(df):
    """
    Volume Breakout: price consolidates in a low-volatility range for 10+
    candles (< 4% spread), then breaks above the consolidation high on a
    2x+ volume spike. EMA7 > EMA25 and RSI < 70 (not yet overbought).

    Returns (detected: bool, strength: 1-5)
      Strength 1: Barely 2x volume
      Strength 5: 3x+ volume, tight consolidation, clean breakout
    """
    try:
        if len(df) < 15:
            return False, 0

        closes = df['close'].tolist()
        volumes = df['volume'].tolist()

        # Consolidation zone: candles [-11:-1] (10 candles before the current)
        consol_closes = closes[-11:-1]
        consol_high = max(consol_closes)
        consol_low = min(consol_closes)
        if consol_low <= 0:
            return False, 0
        consol_range = (consol_high - consol_low) / consol_low
        if consol_range >= 0.04:
            return False, 0

        # Breakout: current close above consolidation high
        current_close = closes[-1]
        if current_close <= consol_high:
            return False, 0

        # Volume spike: current candle volume >= 2x average of consolidation candles
        avg_consol_vol = sum(volumes[-11:-1]) / 10
        if avg_consol_vol <= 0 or volumes[-1] < avg_consol_vol * 2.0:
            return False, 0

        # EMA alignment: EMA7 > EMA25
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        if ema7 <= ema25:
            return False, 0

        # RSI not overbought (< 70)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        if rsi_series.iloc[-1] >= 70:
            return False, 0

        # ── Strength scoring (1-5) ────────────────────────────────────────────
        strength = 1
        vol_ratio = volumes[-1] / avg_consol_vol if avg_consol_vol > 0 else 2.0

        # Very tight consolidation
        if consol_range < 0.02:
            strength += 1
        # Strong volume spike (3x+)
        if vol_ratio >= 3.0:
            strength += 1
        # Clean breakout: close well above consolidation high (0.5%+)
        breakout_pct = (current_close - consol_high) / consol_high
        if breakout_pct >= 0.005:
            strength += 1
        # All premium criteria met
        if consol_range < 0.02 and vol_ratio >= 3.0 and breakout_pct >= 0.005:
            strength = 5

        strength = min(strength, 5)
        return True, strength
    except:
        pass
    return False, 0

# ─── ATR BASED SL/TP (DYNAMIC VOLATILITY) ────────────────────────────────────
def get_sl_tp(df, direction, entry_price):
    """
    Dynamic SL based on current ATR vs 20-candle average ATR.
    Returns (sl, tp1, tp2):
      - TP1 = ATR × 2.0  (50% close, move SL to breakeven)
      - TP2 = ATR × 3.0  (remaining 50%, trailing SL)
    SL multiplier adapts to volatility:
      - High volatility (ratio > 1.5): ATR × 2.0
      - Low  volatility (ratio < 0.7): ATR × 1.0
      - Normal:                        ATR × 1.5
    """
    high_low = df['high'] - df['low']
    atr_series = high_low.rolling(14).mean()
    current_atr = atr_series.iloc[-1]

    # Volatility ratio: current ATR vs 20-candle average of ATR
    avg_atr_20 = atr_series.iloc[-20:].mean() if len(atr_series) >= 20 else current_atr
    volatility_ratio = current_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0

    if volatility_ratio > 1.5:
        sl_multiplier = 2.0   # High volatility — wider SL
        vol_label = "HIGH"
    elif volatility_ratio < 0.7:
        sl_multiplier = 1.0   # Low volatility — tighter SL
        vol_label = "LOW"
    else:
        sl_multiplier = 1.5   # Normal
        vol_label = "NORMAL"

    print(f"📐 Volatility: {vol_label} (ratio={volatility_ratio:.2f}) → SL multiplier={sl_multiplier}x ATR")

    if direction == 'LONG':
        sl   = entry_price - (current_atr * sl_multiplier)
        tp1  = entry_price + (current_atr * 2.0)
        tp2  = entry_price + (current_atr * 3.0)
    else:
        sl   = entry_price + (current_atr * sl_multiplier)
        tp1  = entry_price - (current_atr * 2.0)
        tp2  = entry_price - (current_atr * 3.0)

    return round(sl, 6), round(tp1, 6), round(tp2, 6)

# ─── SUPPORT / RESISTANCE DETECTION ─────────────────────────────────────────
def detect_support_resistance(df):
    """
    Scan the last 50 candles for local highs and lows, cluster them within a
    1% tolerance, and return the strongest support and resistance levels.

    Returns:
        (support_level, resistance_level, support_strength, resistance_strength)
        Strength = number of times price bounced off that level.
    """
    try:
        if len(df) < 10:
            return None, None, 0, 0

        window = df.tail(50)
        closes = window['close'].tolist()
        highs  = window['high'].tolist()
        lows   = window['low'].tolist()
        current_price = closes[-1]

        # Collect local highs (resistance candidates) and lows (support candidates)
        resistance_candidates = []
        support_candidates    = []

        for i in range(1, len(closes) - 1):
            if highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]:
                resistance_candidates.append(highs[i])
            if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]:
                support_candidates.append(lows[i])

        def cluster_levels(levels, tolerance=0.01):
            """Group nearby levels (within tolerance %) and count bounces."""
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
            # Return (avg_level, bounce_count) per cluster
            return [(sum(c) / len(c), len(c)) for c in clusters]

        res_clusters = cluster_levels(resistance_candidates)
        sup_clusters = cluster_levels(support_candidates)

        # Pick the strongest (highest bounce count) level on each side
        best_resistance = max(res_clusters, key=lambda x: x[1]) if res_clusters else (None, 0)
        best_support    = max(sup_clusters, key=lambda x: x[1]) if sup_clusters else (None, 0)

        support_level    = round(best_support[0],    6) if best_support[0]    else None
        resistance_level = round(best_resistance[0], 6) if best_resistance[0] else None
        support_strength    = best_support[1]
        resistance_strength = best_resistance[1]

        return support_level, resistance_level, support_strength, resistance_strength

    except Exception as e:
        print(f"S/R detection error: {e}")
        return None, None, 0, 0


# ─── DIVERGENCE DETECTION ─────────────────────────────────────────────────────
def detect_rsi_divergence(df):
    """
    Scan the last 20 candles for RSI divergence.

    Bullish divergence : price makes a lower low  while RSI makes a higher low
                         → reversal signal for LONG  (+20 if within last 5 candles)
    Bearish divergence : price makes a higher high while RSI makes a lower high
                         → reversal signal for SHORT (+20 if within last 5 candles)

    Returns:
        (divergence_type, candles_back)
        divergence_type : "BULLISH", "BEARISH", or None
        candles_back    : how many candles ago the divergence occurred
    """
    try:
        if len(df) < 25:
            return None, 0

        # Compute RSI
        delta = df['close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs    = gain / (loss + 1e-9)
        rsi_series = (100 - (100 / (1 + rs))).tolist()

        closes = df['close'].tolist()
        window = 20  # candles to look back

        # Reference point: the most recent candle
        ref_close = closes[-1]
        ref_rsi   = rsi_series[-1]

        for i in range(2, window + 1):
            past_close = closes[-i]
            past_rsi   = rsi_series[-i]

            # Bullish divergence: price lower low, RSI higher low
            if ref_close < past_close and ref_rsi > past_rsi:
                return "BULLISH", i - 1

            # Bearish divergence: price higher high, RSI lower high
            if ref_close > past_close and ref_rsi < past_rsi:
                return "BEARISH", i - 1

        return None, 0

    except Exception as e:
        print(f"Divergence detection error: {e}")
        return None, 0


# ─── TREND FILTER (200-EMA ON 1H) ────────────────────────────────────────────
def get_trend_filter(df_1h):
    """
    Determine macro trend using the 200-EMA on the 1h chart.

    Returns:
        "BULLISH"  — price > 200-EMA
        "BEARISH"  — price < 200-EMA
        "NEUTRAL"  — price within 2% of 200-EMA
    """
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
        else:
            return "NEUTRAL"

    except Exception as e:
        print(f"Trend filter error: {e}")
        return "NEUTRAL"


# ─── LIQUIDITY ZONE DETECTION ─────────────────────────────────────────────────
def is_in_liquidity_zone(df, support, resistance):
    """
    Returns True if the current price is within 1.5% of a known support or
    resistance level (i.e. inside a liquidity zone where fills are uncertain).
    Also returns whether the price is breaking out of the zone on volume.

    Returns:
        (in_zone: bool, breakout: bool)
    """
    try:
        current_price = df['close'].iloc[-1]
        volumes       = df['volume'].tolist()
        avg_vol       = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1.0
        current_vol   = volumes[-1]
        high_volume   = current_vol >= avg_vol * 1.5

        in_zone = False
        if support is not None:
            if abs(current_price - support) / support <= 0.015:
                in_zone = True
        if resistance is not None:
            if abs(current_price - resistance) / resistance <= 0.015:
                in_zone = True

        # Breakout: price is near a zone AND volume is elevated
        breakout = in_zone and high_volume

        return in_zone, breakout

    except Exception as e:
        print(f"Liquidity zone error: {e}")
        return False, False


# ─── MULTI-TIMEFRAME CONFIRMATION ────────────────────────────────────────────
def confirm_multi_timeframe(df_15m, df_1h, df_4h):
    """
    Check trend alignment across 3 timeframes for LONG or SHORT direction.

    15m: Entry signal  — EMA7 > EMA25 and RSI 30-60 (LONG)
    1h:  Trend confirm — EMA7 > EMA25 and price > 200-EMA (LONG)
    4h:  Structure     — EMA7 > EMA25 and no recent reversal (LONG)

    Returns (confirmed: bool, alignment_score: 0-100)
    confirmed = True if alignment_score >= 66 (2+ timeframes aligned)
    """
    try:
        aligned_count = 0
        tf_results = {'15m': False, '1h': False, '4h': False}

        # Determine direction from 15m EMA alignment
        ema7_15m  = df_15m['close'].ewm(span=7).mean().iloc[-1]
        ema25_15m = df_15m['close'].ewm(span=25).mean().iloc[-1]
        direction = 'LONG' if ema7_15m > ema25_15m else 'SHORT'

        # ── 15m: Entry signal ────────────────────────────────────────────────
        delta_15m = df_15m['close'].diff()
        gain_15m  = delta_15m.where(delta_15m > 0, 0).rolling(14).mean()
        loss_15m  = (-delta_15m.where(delta_15m < 0, 0)).rolling(14).mean()
        rsi_15m   = (100 - (100 / (1 + gain_15m / (loss_15m + 1e-9)))).iloc[-1]

        if direction == 'LONG':
            if ema7_15m > ema25_15m and 30 <= rsi_15m <= 60:
                aligned_count += 1
                tf_results['15m'] = True
        else:
            if ema7_15m < ema25_15m and 40 <= rsi_15m <= 70:
                aligned_count += 1
                tf_results['15m'] = True

        # ── 1h: Trend confirmation ───────────────────────────────────────────
        if df_1h is not None and len(df_1h) >= 50:
            ema7_1h   = df_1h['close'].ewm(span=7).mean().iloc[-1]
            ema25_1h  = df_1h['close'].ewm(span=25).mean().iloc[-1]
            ema200_1h = df_1h['close'].ewm(span=200).mean().iloc[-1]
            price_1h  = df_1h['close'].iloc[-1]

            if direction == 'LONG':
                if ema7_1h > ema25_1h and price_1h > ema200_1h:
                    aligned_count += 1
                    tf_results['1h'] = True
            else:
                if ema7_1h < ema25_1h and price_1h < ema200_1h:
                    aligned_count += 1
                    tf_results['1h'] = True

        # ── 4h: Structure confirmation ───────────────────────────────────────
        if df_4h is not None and len(df_4h) >= 20:
            ema7_4h  = df_4h['close'].ewm(span=7).mean()
            ema25_4h = df_4h['close'].ewm(span=25).mean()

            if direction == 'LONG':
                ema_aligned_4h = ema7_4h.iloc[-1] > ema25_4h.iloc[-1]
                # No recent reversal: EMA7 has been above EMA25 for last 3 candles
                no_reversal = all(
                    ema7_4h.iloc[-i] > ema25_4h.iloc[-i] for i in range(1, 4)
                )
                if ema_aligned_4h and no_reversal:
                    aligned_count += 1
                    tf_results['4h'] = True
            else:
                ema_aligned_4h = ema7_4h.iloc[-1] < ema25_4h.iloc[-1]
                no_reversal = all(
                    ema7_4h.iloc[-i] < ema25_4h.iloc[-i] for i in range(1, 4)
                )
                if ema_aligned_4h and no_reversal:
                    aligned_count += 1
                    tf_results['4h'] = True

        alignment_score = aligned_count * 33
        alignment_score = min(alignment_score, 100)
        confirmed = alignment_score >= 66

        tf_15m_sym = '✓' if tf_results['15m'] else '✗'
        tf_1h_sym  = '✓' if tf_results['1h']  else '✗'
        tf_4h_sym  = '✓' if tf_results['4h']  else '✗'
        print(
            f"📊 Multi-TF Alignment: 15m {tf_15m_sym} | 1h {tf_1h_sym} | "
            f"4h {tf_4h_sym} ({alignment_score}/100)"
        )
        return confirmed, alignment_score

    except Exception as e:
        print(f"Multi-TF confirmation error: {e}")
        return False, 0


# ─── CONFLUENCE SCORE ─────────────────────────────────────────────────────────
def calculate_confluence_score(df, df_1h, direction, support, resistance,
                                divergence, trend, pattern_detected):
    """
    Count how many of 6 confluence factors are present.

    1. EMA alignment (EMA7 > EMA25 for LONG)
    2. RSI in optimal zone (30-60 LONG, 40-70 SHORT)
    3. Volume spike (RVOL >= 1.5)
    4. Pattern detected (Bull Flag, Death Cross, or Volume Breakout)
    5. Trend aligned (price > 200-EMA for LONG, price < 200-EMA for SHORT)
    6. S/R breakout or divergence

    Returns (confluence_count: 0-6, confluence_score: 0-100)
    """
    try:
        count = 0
        labels = []

        ema7  = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        price = df['close'].iloc[-1]

        delta = df['close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - (100 / (1 + gain / (loss + 1e-9)))).iloc[-1]

        avg_vol = df['volume'].tail(20).mean()
        rvol    = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

        # 1. EMA alignment
        ema_ok = (direction == 'LONG' and ema7 > ema25) or \
                 (direction == 'SHORT' and ema7 < ema25)
        if ema_ok:
            count += 1
            labels.append('EMA ✓')
        else:
            labels.append('EMA ✗')

        # 2. RSI in optimal zone
        rsi_ok = (direction == 'LONG'  and 30 <= rsi <= 60) or \
                 (direction == 'SHORT' and 40 <= rsi <= 70)
        if rsi_ok:
            count += 1
            labels.append('RSI ✓')
        else:
            labels.append('RSI ✗')

        # 3. Volume spike
        if rvol >= 1.5:
            count += 1
            labels.append('Volume ✓')
        else:
            labels.append('Volume ✗')

        # 4. Pattern detected
        if pattern_detected:
            count += 1
            labels.append('Pattern ✓')
        else:
            labels.append('Pattern ✗')

        # 5. Trend aligned (200-EMA on 1h)
        trend_ok = (direction == 'LONG'  and trend == 'BULLISH') or \
                   (direction == 'SHORT' and trend == 'BEARISH')
        if trend_ok:
            count += 1
            labels.append('Trend ✓')
        else:
            labels.append('Trend ✗')

        # 6. S/R breakout or divergence
        sr_div_ok = False
        if resistance is not None and price > resistance and rvol >= 1.5:
            sr_div_ok = True
        if divergence is not None:
            if (direction == 'LONG'  and divergence == 'BULLISH') or \
               (direction == 'SHORT' and divergence == 'BEARISH'):
                sr_div_ok = True
        if sr_div_ok:
            count += 1
            labels.append('S/R ✓')
        else:
            labels.append('S/R ✗')

        confluence_score = round(count * (100 / 6))
        label_str = ' | '.join(labels)
        print(f"🔗 Confluence: {count}/6 ({label_str}) = {confluence_score}/100")
        return count, confluence_score

    except Exception as e:
        print(f"Confluence score error: {e}")
        return 0, 0


# ─── RISK/REWARD CONFIRMATION ─────────────────────────────────────────────────
def confirm_risk_reward(entry_price, sl, tp1, tp2, direction):
    """
    Calculate R/R ratio for TP1 and TP2.

    LONG:  R/R = (tp - entry) / (entry - sl)
    SHORT: R/R = (entry - tp) / (sl - entry)

    Returns (rr_ratio: float, confirmed: bool)
    confirmed = True if rr_ratio >= 1.5
    """
    try:
        if direction == 'LONG':
            risk   = entry_price - sl
            rr_tp1 = (tp1 - entry_price) / risk if risk > 0 else 0.0
            rr_tp2 = (tp2 - entry_price) / risk if risk > 0 else 0.0
        else:
            risk   = sl - entry_price
            rr_tp1 = (entry_price - tp1) / risk if risk > 0 else 0.0
            rr_tp2 = (entry_price - tp2) / risk if risk > 0 else 0.0

        confirmed = rr_tp1 >= 1.5
        status    = '✓ Confirmed' if confirmed else '✗ Below threshold'
        print(
            f"💰 Risk/Reward: {rr_tp1:.1f}:1 (TP1) | {rr_tp2:.1f}:1 (TP2) "
            f"{status}"
        )
        return rr_tp1, confirmed

    except Exception as e:
        print(f"R/R confirmation error: {e}")
        return 0.0, False


# ─── VOLATILITY REGIME CONFIRMATION ──────────────────────────────────────────
def confirm_volatility_regime(df, pattern_type, direction):
    """
    Classify current volatility regime and check if the pattern fits.

    HIGH   (ratio > 1.5): Only BREAKOUT patterns (Volume Breakout, Bull Flag)
    NORMAL (0.7-1.5):     All patterns allowed
    LOW    (ratio < 0.7): Only BOUNCE patterns (S/R bounces, divergence reversals)

    Returns (regime: str, confirmed: bool)
    """
    try:
        high_low    = df['high'] - df['low']
        atr_series  = high_low.rolling(14).mean()
        current_atr = atr_series.iloc[-1]
        avg_atr_20  = atr_series.iloc[-20:].mean() if len(atr_series) >= 20 else current_atr
        ratio       = current_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0

        if ratio > 1.5:
            regime = 'HIGH'
        elif ratio < 0.7:
            regime = 'LOW'
        else:
            regime = 'NORMAL'

        # Classify pattern type
        breakout_patterns = {'bull_flag', 'volume_breakout'}
        bounce_patterns   = {'sr_bounce', 'divergence_reversal', 'death_cross'}

        if regime == 'HIGH':
            confirmed = pattern_type in breakout_patterns
        elif regime == 'LOW':
            confirmed = pattern_type in bounce_patterns
        else:
            confirmed = True  # NORMAL: all patterns allowed

        status = '✓ Confirmed' if confirmed else '✗ Mismatch'
        print(
            f"🌪️ Volatility Regime: {regime} (ratio={ratio:.2f}) | "
            f"Pattern: {pattern_type} {status}"
        )
        return regime, confirmed

    except Exception as e:
        print(f"Volatility regime error: {e}")
        return 'NORMAL', True


# ─── MATH SCORE ───────────────────────────────────────────────────────────────
def calculate_math_score(df, df_1h=None, df_4h=None):
    """
    Calculate a composite math score for a potential trade signal.

    Integrates all detection layers:
      1. Support / Resistance detection  (penalty near zones, bonus on breakout)
      2. RSI Divergence detection        (bonus for confirmed divergence)
      3. 200-EMA Trend Filter (1h)       (penalty counter-trend, bonus aligned)
      4. Liquidity Zone detection        (penalty inside zone, bonus on breakout)
      5. Pattern Strength scoring        (partial bonus for strength 3-4, full for 5)
      6. Multi-Timeframe Confirmation    (penalty -20 if alignment < 66)
      7. Confluence Score                (penalty if confluence_count < 4)
      8. Risk/Reward Confirmation        (penalty -25 if R/R < 1.5)
      9. Volatility Regime Confirmation  (penalty -20 if pattern mismatches regime)

    Returns:
        (score, direction, rvol, rsi, support, resistance, divergence_type, trend,
         confluence_count, multi_tf_score, rr_ratio, vol_regime)
    """
    # ── Base indicators ──────────────────────────────────────────────────────
    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_7']  = df['close'].ewm(span=7).mean()
    df['ema_25'] = df['close'].ewm(span=25).mean()

    # RSI
    delta = df['close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs    = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    price = df['close'].iloc[-1]
    ema7  = df['ema_7'].iloc[-1]
    ema25 = df['ema_25'].iloc[-1]
    rsi   = df['rsi'].iloc[-1]

    # Volume
    avg_vol = df['volume'].tail(20).mean()
    rvol    = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

    # Direction
    direction = 'LONG' if ema7 > ema25 else 'SHORT'

    # Score starts at 30
    score = 30

    # ── EMA alignment ────────────────────────────────────────────────────────
    if direction == 'LONG' and ema7 > ema25:
        score += 15
    elif direction == 'SHORT' and ema7 < ema25:
        score += 15

    # ── RSI ──────────────────────────────────────────────────────────────────
    if direction == 'LONG' and 30 < rsi < 60:
        score += 15
    elif direction == 'SHORT' and 40 < rsi < 70:
        score += 15

    # ── RVOL ─────────────────────────────────────────────────────────────────
    if rvol >= 1.5:
        score += 15
    elif rvol >= 1.2:
        score += 8

    # ── RSI extreme penalty ──────────────────────────────────────────────────
    if rsi > 85 or rsi < 15:
        score -= 40

    # ── Pattern 14 penalty ───────────────────────────────────────────────────
    if is_false_recovery(df):
        score -= 30
        print(f"⚠️ Pattern 14 detected — False Recovery penalty applied")

    # ── Bull Flag bonus (strength-weighted, LONG) ─────────────────────────────
    bull_flag, bf_strength = detect_bull_flag(df)
    if bull_flag:
        if bf_strength >= 5:
            bf_bonus = 20
        elif bf_strength >= 3:
            bf_bonus = 10
        else:
            bf_bonus = 0   # Strength 1-2: no bonus
        if bf_bonus > 0:
            score += bf_bonus
            print(f"🚩 Bull Flag (Strength {bf_strength}/5) — +{bf_bonus} bonus applied")
        else:
            print(f"🚩 Bull Flag (Strength {bf_strength}/5) — below threshold, no bonus")
    else:
        print(f"🚩 Bull Flag: not detected")

    # ── Death Cross bonus (strength-weighted, SHORT) ──────────────────────────
    death_cross, dc_strength = detect_death_cross(df)
    if death_cross:
        if dc_strength >= 5:
            dc_bonus = 20
        elif dc_strength >= 3:
            dc_bonus = 10
        else:
            dc_bonus = 0
        if dc_bonus > 0:
            score += dc_bonus
            print(f"💀 Death Cross (Strength {dc_strength}/5) — +{dc_bonus} bonus applied")
        else:
            print(f"💀 Death Cross (Strength {dc_strength}/5) — below threshold, no bonus")
    else:
        print(f"💀 Death Cross: not detected")

    # ── Volume Breakout bonus (strength-weighted, LONG) ───────────────────────
    vol_breakout, vb_strength = detect_volume_breakout(df)
    if vol_breakout:
        if vb_strength >= 5:
            vb_bonus = 15
        elif vb_strength >= 3:
            vb_bonus = 8
        else:
            vb_bonus = 0
        if vb_bonus > 0:
            score += vb_bonus
            print(f"📈 Volume Breakout (Strength {vb_strength}/5) — +{vb_bonus} bonus applied")
        else:
            print(f"📈 Volume Breakout (Strength {vb_strength}/5) — below threshold, no bonus")
    else:
        print(f"📈 Volume Breakout: not detected")

    # Determine active pattern type for volatility regime check
    if bull_flag:
        active_pattern = 'bull_flag'
    elif vol_breakout:
        active_pattern = 'volume_breakout'
    elif death_cross:
        active_pattern = 'death_cross'
    else:
        active_pattern = 'none'

    any_pattern_detected = bull_flag or death_cross or vol_breakout

    # ════════════════════════════════════════════════════════════════════════
    # DETECTION LAYERS (S/R → divergence → trend → liquidity)
    # ════════════════════════════════════════════════════════════════════════

    # ── 1. Support / Resistance ───────────────────────────────────────────────
    support, resistance, sup_strength, res_strength = detect_support_resistance(df)
    print(f"📊 S/R — Support: {support} (×{sup_strength}) | Resistance: {resistance} (×{res_strength})")

    if support is not None and price > 0:
        near_support    = abs(price - support)    / price <= 0.02
        near_resistance = (resistance is not None and
                           abs(price - resistance) / price <= 0.02)

        if near_support or near_resistance:
            score -= 10
            print(f"⚠️ Price within 2% of S/R level — -10 penalty applied")

        if (resistance is not None and
                price > resistance and
                rvol >= 1.5):
            score += 15
            print(f"🚀 Liquidity breakout above resistance on volume — +15 bonus applied")

    # ── 2. RSI Divergence ─────────────────────────────────────────────────────
    divergence_type, candles_back = detect_rsi_divergence(df)
    if divergence_type:
        print(f"🔀 Divergence: {divergence_type} ({candles_back} candles back)")
        if candles_back <= 5:
            if divergence_type == "BULLISH" and direction == "LONG":
                score += 20
                print(f"✅ Bullish divergence confirmed (LONG) — +20 bonus applied")
            elif divergence_type == "BEARISH" and direction == "SHORT":
                score += 20
                print(f"✅ Bearish divergence confirmed (SHORT) — +20 bonus applied")
            else:
                print(f"ℹ️ Divergence detected but direction mismatch — no bonus")
        else:
            print(f"ℹ️ Divergence too old ({candles_back} candles) — no bonus")
    else:
        print(f"🔀 Divergence: none detected")
        divergence_type = None

    # ── 3. Trend Confirmation (200-EMA on 1h) ────────────────────────────────
    trend = get_trend_filter(df_1h)
    print(f"📈 1H Trend (200-EMA): {trend}")

    if direction == "LONG":
        if trend == "BEARISH":
            score -= 30
            print(f"⛔ Counter-trend LONG in BEARISH market — -30 penalty applied")
        elif trend == "BULLISH":
            score += 10
            print(f"✅ Trend-aligned LONG in BULLISH market — +10 bonus applied")
    elif direction == "SHORT":
        if trend == "BULLISH":
            score -= 30
            print(f"⛔ Counter-trend SHORT in BULLISH market — -30 penalty applied")
        elif trend == "BEARISH":
            score += 10
            print(f"✅ Trend-aligned SHORT in BEARISH market — +10 bonus applied")

    # ── 4. Liquidity Zone ────────────────────────────────────────────────────
    in_zone, liq_breakout = is_in_liquidity_zone(df, support, resistance)
    if liq_breakout:
        score += 15
        print(f"💧 Liquidity breakout from zone on volume — +15 bonus applied")
    elif in_zone:
        score -= 15
        print(f"⚠️ Price inside liquidity zone — -15 penalty applied")
    else:
        print(f"💧 Liquidity zone: clear")

    # ════════════════════════════════════════════════════════════════════════
    # ADVANCED CONFIRMATION LAYERS (5 new mechanisms)
    # ════════════════════════════════════════════════════════════════════════

    # ── 5. Multi-Timeframe Confirmation ──────────────────────────────────────
    multi_tf_confirmed, multi_tf_score = confirm_multi_timeframe(df, df_1h, df_4h)
    if not multi_tf_confirmed:
        score -= 20
        print(f"⚠️ Multi-TF alignment below 66 — -20 penalty applied")

    # ── 6. Confluence Score ───────────────────────────────────────────────────
    confluence_count, confluence_score_val = calculate_confluence_score(
        df, df_1h, direction, support, resistance,
        divergence_type, trend, any_pattern_detected
    )
    if confluence_count < 4:
        penalty = (4 - confluence_count) * 10
        score -= penalty
        print(f"⚠️ Confluence {confluence_count}/6 (below 4) — -{penalty} penalty applied")

    # ── 7. Risk/Reward Confirmation (requires SL/TP — use ATR-based estimate) ─
    # Compute a provisional SL/TP to evaluate R/R before final execution
    high_low    = df['high'] - df['low']
    atr_series  = high_low.rolling(14).mean()
    current_atr = atr_series.iloc[-1]
    avg_atr_20  = atr_series.iloc[-20:].mean() if len(atr_series) >= 20 else current_atr
    vol_ratio   = current_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0
    sl_mult     = 2.0 if vol_ratio > 1.5 else (1.0 if vol_ratio < 0.7 else 1.5)

    if direction == 'LONG':
        est_sl  = price - (current_atr * sl_mult)
        est_tp1 = price + (current_atr * 2.0)
        est_tp2 = price + (current_atr * 3.0)
    else:
        est_sl  = price + (current_atr * sl_mult)
        est_tp1 = price - (current_atr * 2.0)
        est_tp2 = price - (current_atr * 3.0)

    rr_ratio, rr_confirmed = confirm_risk_reward(price, est_sl, est_tp1, est_tp2, direction)
    if not rr_confirmed:
        score -= 25
        print(f"⚠️ R/R below 1.5:1 — -25 penalty applied")

    # ── 8. Volatility Regime Confirmation ────────────────────────────────────
    vol_regime, vol_regime_confirmed = confirm_volatility_regime(df, active_pattern, direction)
    if not vol_regime_confirmed:
        score -= 20
        print(f"⚠️ Pattern mismatches volatility regime — -20 penalty applied")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(
        f"✅ SCORE CONFIRMATION SUMMARY: "
        f"Confluence {confluence_count}/6 | "
        f"Multi-TF {multi_tf_score}/100 | "
        f"R/R {rr_ratio:.1f}:1 | "
        f"Vol Regime {vol_regime} {'✓' if vol_regime_confirmed else '✗'}"
    )

    return (score, direction, rvol, rsi, support, resistance, divergence_type, trend,
            confluence_count, multi_tf_score, rr_ratio, vol_regime)

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
def log_trade(symbol, side, entry, sl, tp1, tp2, score,
              support=None, resistance=None, divergence=None,
              trend=None, dynamic_sl=None,
              confluence_count=None, multi_tf_score=None,
              rr_ratio=None, vol_regime=None):
    """
    Persist a trade to the database with all enriched metadata.

    Parameters
    ----------
    symbol, side, entry, sl, tp1, tp2, score : core trade fields
    support, resistance : S/R levels detected at entry
    divergence          : "BULLISH", "BEARISH", or None
    trend               : "BULLISH", "BEARISH", or "NEUTRAL"
    dynamic_sl          : actual SL value after volatility adjustment
    confluence_count    : number of confluence factors (0-6)
    multi_tf_score      : multi-timeframe alignment score (0-100)
    rr_ratio            : risk/reward ratio for TP1
    vol_regime          : volatility regime ("HIGH", "NORMAL", "LOW")
    """
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            """INSERT INTO trades
               (time, symbol, side, entry, sl, tp1, tp2, score,
                support, resistance, divergence, trend, dynamic_sl, entry_time,
                confluence_count, multi_tf_score, rr_ratio, vol_regime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, symbol, side, entry, sl, tp1, tp2, score,
             support, resistance, divergence, trend, dynamic_sl, now,
             confluence_count, multi_tf_score, rr_ratio, vol_regime)
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
