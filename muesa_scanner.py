import os
import time
import asyncio
import ccxt
import pandas as pd
from datetime import datetime, timedelta
from muesa_logic import (
    init_db, can_take_trade, is_on_cooldown, passes_volume_filter,
    calculate_math_score, call_claude_ai, get_sl_tp, log_ghost_trade,
    increment_trade_count, MIN_VOLUME_USDT
)
from muesa_telegram import system_alert, weekly_analysis, daily_summary

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CLAUDE_CALL_THRESHOLD = 60
FINAL_TRADE_THRESHOLD = 75
CACHE_TTL = 60            # 1 minute cache
COIN_ANALYSIS_DELAY = 0.3 # Seconds between coins
MAX_COINS_TO_SCAN = 100   # Top 100 by volume only

# ─── CANDLE CACHE ─────────────────────────────────────────────────────────────
_candle_cache: dict = {}

def _fetch_ohlcv_cached(exchange, symbol: str, timeframe: str, limit: int) -> list:
    cache_key = (symbol, timeframe)
    now = time.monotonic()
    cached = _candle_cache.get(cache_key)
    if cached is not None:
        candles, fetched_at = cached
        if now - fetched_at < CACHE_TTL:
            return candles
    candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    _candle_cache[cache_key] = (candles, now)
    return candles

# ─── WAIT FOR CANDLE CLOSE ────────────────────────────────────────────────────
def seconds_until_next_15m_close():
    now = datetime.utcnow()
    minutes = now.minute
    seconds = now.second
    next_boundary = ((minutes // 15) + 1) * 15
    if next_boundary >= 60:
        minutes_to_wait = 60 - minutes
    else:
        minutes_to_wait = next_boundary - minutes
    total_seconds = (minutes_to_wait * 60) - seconds + 5
    return total_seconds

# ─── EMA CHECKS ───────────────────────────────────────────────────────────────
def check_1d_ema(exchange, symbol, direction):
    try:
        candles = _fetch_ohlcv_cached(exchange, symbol, '1d', limit=120)
        df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume'])
        ema7  = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        ema99 = df['close'].ewm(span=99).mean().iloc[-1]
        if direction == 'LONG'  and ema7 < ema25 < ema99:
            return False
        if direction == 'SHORT' and ema7 > ema25 > ema99:
            return False
        return True
    except Exception as e:
        print(f"1D EMA error {symbol}: {e}")
        return False

def check_4h_1h_ema(exchange, symbol, direction):
    try:
        for tf in ['4h', '1h']:
            candles = _fetch_ohlcv_cached(exchange, symbol, tf, limit=50)
            df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume'])
            ema7  = df['close'].ewm(span=7).mean().iloc[-1]
            ema25 = df['close'].ewm(span=25).mean().iloc[-1]
            if direction == 'LONG'  and ema7 < ema25:
                return False
            if direction == 'SHORT' and ema7 > ema25:
                return False
        return True
    except Exception as e:
        print(f"4H/1H EMA error {symbol}: {e}")
        return False

# ─── FETCH 15M CANDLES ────────────────────────────────────────────────────────
def get_15m_candles(exchange, symbol):
    try:
        candles = _fetch_ohlcv_cached(exchange, symbol, '15m', limit=100)
        df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume'])
        return df
    except Exception as e:
        print(f"15m candle error {symbol}: {e}")
        return None

# ─── ANALYSE COIN ─────────────────────────────────────────────────────────────
async def analyse_coin(exchange, symbol, volume_usdt):
    try:
        # Filter 1 — Cooldown
        if is_on_cooldown(symbol):
            return

        # Filter 2 — Max trades
        if not can_take_trade():
            print("🛑 Max 5 trades reached for today")
            return

        # Get 15m candles
        df = get_15m_candles(exchange, symbol)
        if df is None or len(df) < 50:
            return

        # Fetch 1h candles for 200-EMA trend filter
        df_1h = None
        try:
            candles_1h = _fetch_ohlcv_cached(exchange, symbol, '1h', limit=250)
            df_1h = pd.DataFrame(candles_1h, columns=['time','open','high','low','close','volume'])
        except Exception as e:
            print(f"1h candle fetch error {symbol}: {e}")

        # Math score
        score, direction, rvol, rsi, support, resistance, divergence, trend = \
            calculate_math_score(df, df_1h=df_1h)
        print(
            f"📊 {symbol} | Score: {score} | Direction: {direction} | "
            f"RSI: {rsi:.1f} | RVOL: {rvol:.2f} | Trend: {trend} | "
            f"Divergence: {divergence} | S: {support} | R: {resistance}"
        )

        if score < CLAUDE_CALL_THRESHOLD:
            log_ghost_trade(symbol, score, "Below 60 threshold")
            return

        # Filter 3 — 1D EMA block
        if not check_1d_ema(exchange, symbol, direction):
            print(f"🚫 {symbol} blocked by 1D EMA filter")
            log_ghost_trade(symbol, score, "1D EMA block")
            return

        # Filter 4 — 4H and 1H EMA
        if not check_4h_1h_ema(exchange, symbol, direction):
            print(f"🚫 {symbol} blocked by 4H/1H EMA filter")
            log_ghost_trade(symbol, score, "4H/1H EMA block")
            return

        # Claude API call
        loop = asyncio.get_event_loop()
        final_score = await loop.run_in_executor(
            None, call_claude_ai, symbol, score, direction, rsi, rvol
        )
        print(f"🤖 {symbol} Final Score: {final_score}")

        if final_score < FINAL_TRADE_THRESHOLD:
            log_ghost_trade(symbol, final_score, "Below 75 final threshold")
            return

        # Get dynamic SL / TP1 / TP2
        entry_price = df['close'].iloc[-1]
        sl, tp1, tp2 = get_sl_tp(df, direction, entry_price)

        print(
            f"✅ TRADE SIGNAL: {symbol} | {direction} | Entry: {entry_price} "
            f"| SL: {sl} | TP1: {tp1} | TP2: {tp2}"
        )

        # Execute trade
        from muesa_trader import execute_trade
        execute_trade(
            symbol, direction, entry_price, sl, tp1, tp2, final_score,
            support=support, resistance=resistance,
            divergence=divergence, trend=trend
        )

    except Exception as e:
        print(f"Analyse error {symbol}: {e}")

# ─── MAIN SCANNER LOOP ────────────────────────────────────────────────────────
async def scan_market_live():
    init_db()
    print("🚀 MUESA Scanner Started!")

    # REST exchange
    exchange = ccxt.binance({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_SECRET_KEY'),
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

    print("🚀 MUESA ENGINE ONLINE")

    # Trackers
    last_weekly_report = datetime.utcnow().date()
    last_daily_summary = datetime.utcnow().date()

    try:
        while True:
            now = datetime.utcnow()
            today = now.date()

            # ── Weekly report — every Sunday ──────────────────────────────────
            if today.weekday() == 6 and today != last_weekly_report:
                print("📊 Sending weekly analysis...")
                weekly_analysis()
                last_weekly_report = today

            # ── Daily summary — every midnight UTC ───────────────────────────
            if today != last_daily_summary:
                try:
                    import sqlite3
                    conn = sqlite3.connect('muesa_data.db')
                    c = conn.cursor()
                    yesterday = str(last_daily_summary)
                    c.execute("SELECT count FROM daily_stats WHERE date=?", (yesterday,))
                    row = c.fetchone()
                    trades_today = row[0] if row else 0
                    c.execute("SELECT COUNT(*) FROM trades")
                    total = c.fetchone()[0]
                    c.execute("SELECT COUNT(*) FROM ghost_trades WHERE time >= ?", (yesterday,))
                    skipped = c.fetchone()[0]
                    conn.close()
                    daily_summary(trades_today, total, skipped)
                except Exception as e:
                    print(f"Daily summary error: {e}")
                last_daily_summary = today

            # ── Wait for next 15m candle close ────────────────────────────────
            wait_seconds = seconds_until_next_15m_close()
            print(f"\n⏳ Next candle close in {wait_seconds:.0f}s [{now.strftime('%H:%M:%S UTC')}]")
            await asyncio.sleep(wait_seconds)

            # ── Scan top coins by volume ──────────────────────────────────────
            scan_time = datetime.utcnow()
            print(f"\n🔍 MUESA Scanning at candle close [{scan_time.strftime('%H:%M:%S UTC')}]")

            # Clear cache for fresh data
            _candle_cache.clear()

            # Fetch all tickers
            tickers = exchange.fetch_tickers()

            # Filter by volume and sort — top 100 only
            usdt_tickers = {
                symbol: data for symbol, data in tickers.items()
                if symbol.endswith('/USDT:USDT')
                and float(data.get('quoteVolume', 0)) >= MIN_VOLUME_USDT
            }

            sorted_tickers = sorted(
                usdt_tickers.items(),
                key=lambda x: float(x[1].get('quoteVolume', 0)),
                reverse=True
            )[:MAX_COINS_TO_SCAN]

            print(f"📡 Scanning top {len(sorted_tickers)} coins by volume")

            for symbol, data in sorted_tickers:
                volume_usdt = float(data.get('quoteVolume', 0))
                await analyse_coin(exchange, symbol, volume_usdt)
                await asyncio.sleep(COIN_ANALYSIS_DELAY)

            print(f"✅ Scan complete!")

    except Exception as e:
        print(f"Scanner error: {e}")
        system_alert(f"⚠️ MUESA Scanner Error: {e}")

if __name__ == "__main__":
    asyncio.run(scan_market_live())
