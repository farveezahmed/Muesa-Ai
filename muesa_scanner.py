import os
import time
import asyncio
import ccxt.pro as ccxt
import ccxt as ccxt_sync
import pandas as pd
from datetime import datetime
from muesa_logic import (
    init_db, can_take_trade, is_on_cooldown, passes_volume_filter,
    calculate_math_score, call_claude_ai, get_sl_tp, log_ghost_trade,
    increment_trade_count
)
from muesa_telegram import system_alert

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CLAUDE_CALL_THRESHOLD = 60
FINAL_TRADE_THRESHOLD = 75
SCAN_INTERVAL = 900       # 15 minutes
CACHE_TTL = 300           # Cache candles for 5 minutes
COIN_ANALYSIS_DELAY = 0.5 # Seconds to sleep between coin analyses

# ─── CANDLE CACHE ─────────────────────────────────────────────────────────────
# Structure: { (symbol, timeframe): (candles_list, fetched_at_timestamp) }
_candle_cache: dict = {}

def _fetch_ohlcv_cached(exchange, symbol: str, timeframe: str, limit: int) -> list:
    """
    Return cached OHLCV candles for (symbol, timeframe) if the cached copy is
    younger than CACHE_TTL seconds.  Otherwise fetch fresh data from the
    exchange, store it in the cache, and return it.

    Using a single fetch point for every timeframe means that even when
    check_1d_ema(), check_4h_1h_ema(), and get_15m_candles() all run for the
    same coin inside one scan cycle, only the first call per timeframe hits
    the REST API — subsequent calls within the TTL window are served from
    memory, cutting API traffic from 4 calls/coin down to 1 call/coin on
    repeat scans.
    """
    cache_key = (symbol, timeframe)
    now = time.monotonic()

    cached = _candle_cache.get(cache_key)
    if cached is not None:
        candles, fetched_at = cached
        age = now - fetched_at
        if age < CACHE_TTL:
            return candles

    # Cache miss or expired — fetch from exchange
    candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    _candle_cache[cache_key] = (candles, now)
    return candles

# ─── EMA CHECKS ───────────────────────────────────────────────────────────────
def check_1d_ema(exchange, symbol, direction):
    """
    Check daily EMA alignment.  30 candles is sufficient to produce stable
    EMA-7, EMA-25, and EMA-99 tail values (pandas ewm uses all available rows
    regardless of span), and fetching fewer candles reduces payload size.
    """
    try:
        candles = _fetch_ohlcv_cached(exchange, symbol, '1d', limit=30)
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
            candles = _fetch_ohlcv_cached(exchange, symbol, tf, limit=30)
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
def analyse_coin(exchange, symbol, volume_usdt):
    try:
        # Filter 1 — Volume
        if not passes_volume_filter(volume_usdt):
            return

        # Filter 2 — Cooldown
        if is_on_cooldown(symbol):
            return

        # Filter 3 — Max trades
        if not can_take_trade():
            print("🛑 Max 5 trades reached for today")
            return

        # Get 15m candles (served from cache on repeat scans)
        df = get_15m_candles(exchange, symbol)
        if df is None or len(df) < 50:
            return

        # Math score
        score, direction, rvol, rsi = calculate_math_score(df)
        print(f"📊 {symbol} | Score: {score} | Direction: {direction} | RSI: {rsi:.1f} | RVOL: {rvol:.2f}")

        if score < CLAUDE_CALL_THRESHOLD:
            log_ghost_trade(symbol, score, "Below 60 threshold")
            return

        # Filter 4 — 1D EMA block (served from cache on repeat scans)
        if not check_1d_ema(exchange, symbol, direction):
            print(f"🚫 {symbol} blocked by 1D EMA filter")
            log_ghost_trade(symbol, score, "1D EMA block")
            return

        # Filter 5 — 4H and 1H EMA (served from cache on repeat scans)
        if not check_4h_1h_ema(exchange, symbol, direction):
            print(f"🚫 {symbol} blocked by 4H/1H EMA filter")
            log_ghost_trade(symbol, score, "4H/1H EMA block")
            return

        # Claude API call
        final_score = call_claude_ai(symbol, score, direction, rsi, rvol)
        print(f"🤖 {symbol} Final Score: {final_score}")

        if final_score < FINAL_TRADE_THRESHOLD:
            log_ghost_trade(symbol, final_score, "Below 75 final threshold")
            return

        # Get SL/TP
        entry_price = df['close'].iloc[-1]
        sl, tp = get_sl_tp(df, direction, entry_price)

        print(f"✅ TRADE SIGNAL: {symbol} | {direction} | Entry: {entry_price} | SL: {sl} | TP: {tp}")

        # Execute trade
        from muesa_trader import execute_trade
        execute_trade(symbol, direction, entry_price, sl, tp, final_score)

    except Exception as e:
        print(f"Analyse error {symbol}: {e}")

# ─── MAIN SCANNER LOOP ────────────────────────────────────────────────────────
async def scan_market_live():
    # Init database
    init_db()
    system_alert("🚀 MUESA Scanner Started!")

    # Sync exchange for candle data
    sync_exchange = ccxt_sync.binance({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_SECRET_KEY'),
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

    # Async exchange for live tickers
    async_exchange = ccxt.binance({
        'options': {'defaultType': 'future'}
    })

    print("🚀 MUESA WEBSOCKET ENGINE ONLINE")

    try:
        while True:
            print(f"\n🔍 MUESA Scanning Market...")
            tickers = await async_exchange.watch_tickers()

            for symbol, data in tickers.items():
                if not symbol.endswith('/USDT:USDT'):
                    continue
                volume_usdt = data.get('quoteVolume', 0)
                analyse_coin(sync_exchange, symbol, volume_usdt)
                # Throttle requests to stay within Binance rate limits
                time.sleep(COIN_ANALYSIS_DELAY)

            print(f"⏳ Resting {SCAN_INTERVAL//60} minutes...")
            await asyncio.sleep(SCAN_INTERVAL)

    except Exception as e:
        print(f"Scanner error: {e}")
        system_alert(f"⚠️ MUESA Scanner Error: {e}")
    finally:
        await async_exchange.close()

if __name__ == "__main__":
    asyncio.run(scan_market_live())
