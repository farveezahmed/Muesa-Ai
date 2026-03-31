import ccxt.async_support as ccxt_async
import ccxt
import asyncio
import pandas as pd
import os
from muesa_logic import init_db, calculate_math_score, call_claude_ai, calculate_atr, get_structural_sl, check_cooldown, log_ghost_trade

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

async def fetch_data(exchange, symbol, timeframe):
    try:
        bars = await exchange.fetch_ohlcv(symbol, timeframe, limit=30)
        return pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
    except: return None

async def check_mtf_confluence(exchange, symbol, base_direction):
    for tf in ['1h', '4h']: # Simplified for speed
        df = await fetch_data(exchange, symbol, tf)
        if df is None: return False
        score, direction, _ = calculate_math_score(df)
        if direction != base_direction: return False
    return True

async def scan_market():
    init_db()
    async_ex = ccxt_async.binance({'apiKey': API_KEY, 'secret': SECRET_KEY, 'options': {'defaultType': 'future'}})
    sync_ex = ccxt.binance({'apiKey': API_KEY, 'secret': SECRET_KEY, 'options': {'defaultType': 'future'}})
    
    while True:
        try:
            tickers = await async_ex.fetch_tickers()
            # Volume Filter: 50M (50,000,000)
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 50000000]
            
            for symbol in active_symbols:
                if check_cooldown(symbol): continue
                df_15m = await fetch_data(async_ex, symbol, '15m')
                if df_15m is None: continue
                
                score, direction, rvol = calculate_math_score(df_15m)
                
                if score >= 60 and rvol >= 2.0:
                    final_score = call_claude_ai(symbol, '15m', score)
                    if final_score >= 75:
                        if await check_mtf_confluence(async_ex, symbol, direction):
                            atr = calculate_atr(df_15m)
                            sl = get_structural_sl(df_15m, direction, atr)
                            price = df_15m['close'].iloc[-1]
                            print(f"🔥 SETUP: {symbol} {direction} Score: {final_score}")
                            # Execute Trade logic here
                        else: log_ghost_trade(symbol, final_score, "MTF Failed")
                    else: log_ghost_trade(symbol, final_score, "AI Rejected")
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
