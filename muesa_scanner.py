import os
import asyncio
import ccxt.pro as ccxt
import ccxt as ccxt_sync
import pandas as pd
from muesa_logic import (
    init_db, can_take_trade, is_on_cooldown, passes_volume_filter,
    calculate_math_score, call_claude_ai, get_sl_tp, log_ghost_trade,
    increment_trade_count
)
from muesa_telegram import system_alert

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CLAUDE_CALL_THRESHOLD = 60
FINAL_TRADE_THRESHOLD = 75
SCAN_INTERVAL = 900  # 15 minutes

# ─── EMA CHECKS ───────────────────────────────────────────────────────────────
def check_1d_ema(exchange, symbol, direction):
    try:
        candles = exchange.fetch_ohlcv(symbol, '1d', limit=120)
        df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume'])
        ema7 = df['close'].ewm(span=7).mean().iloc[-1]
        ema25 = df['close'].ewm(span=25).mean().iloc[-1]
        ema99 = df['close'].ewm(span=99).mean().iloc[-1]
        if direction == 'LONG' and ema7 < ema25 < ema99:
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
            candles = exchange.fetch_ohlcv(symbol, tf, limit=50)
            df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume'])
            ema7 = df['close'].ewm(span=7).mean().iloc[-1]
            ema25 = df['close'].ewm(span=25).mean().iloc[-1]
            if direction == 'LONG' and ema7 < ema25:
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
        candles = exchange.fetch_ohlcv(symbol, '15m', limit=100)
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

        # Get 15m candles
        df = get_15m_candles(exchange, symbol)
        if df is None or len(df) < 50:
            return

        # Math score
        score, direction, rvol, rsi = calculate_math_score(df)
        print(f"📊 {symbol} | Score: {score} | Direction: {direction} | RSI: {rsi:.1f} | RVOL: {rvol:.2f}")

        if score < CLAUDE_CALL_THRESHOLD:
            log_ghost_trade(symbol, score, "Below 60 threshold")
            return

        # Filter 4 — 1D EMA block
        if not check_1d_ema(exchange, symbol, direction):
            print(f"🚫 {symbol} blocked by 1D EMA filter")
            log_ghost_trade(symbol, score, "1D EMA block")
            return

        # Filter 5 — 4H and 1H EMA
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

            print(f"⏳ Resting {SCAN_INTERVAL//60} minutes...")
            await asyncio.sleep(SCAN_INTERVAL)

    except Exception as e:
        print(f"Scanner error: {e}")
        system_alert(f"⚠️ MUESA Scanner Error: {e}")
    finally:
        await async_exchange.close()

if __name__ == "__main__":
    asyncio.run(scan_market_live())
