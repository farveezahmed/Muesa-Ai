import ccxt.async_support as ccxt_async
import ccxt
import asyncio
import pandas as pd
import os
from muesa_logic import init_db, calculate_math_score, call_claude_ai, calculate_atr, get_structural_sl, check_cooldown, log_ghost_trade
from muesa_trader import execute_atomic_trade, bodyguard_monitor

# Pulling API Keys from Railway Environment Variables securely
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

async def fetch_data(exchange, symbol, timeframe):
    try:
        bars = await exchange.fetch_ohlcv(symbol, timeframe, limit=30)
        df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
        return df
    except:
        return None

async def check_mtf_confluence(exchange, symbol, base_direction):
    """Ensures 1D, 4H, and 1H are also 75+ and match direction."""
    timeframes = ['1h', '4h', '1d']
    for tf in timeframes:
        df = await fetch_data(exchange, symbol, tf)
        if df is None: return False
        score, direction, _ = calculate_math_score(df)
        if direction != base_direction or call_claude_ai(symbol, tf, score) < 75:
            return False
    return True

async def scan_market():
    init_db()
    async_ex = ccxt_async.binance({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})
    sync_ex = ccxt.binance({'apiKey': API_KEY, 'secret': SECRET_KEY})
    
    print("🚀 MUESA 24/7 ONLINE | Mode: Bi-Directional | Compounding Active")
    
    while True:
        print("\n--- Hunting: Scanning Global Futures ---")
        try:
            tickers = await async_ex.fetch_tickers()
            # Filter: Only USDT pairs with > $5M 24h Volume
            active_symbols = [s for s, t in tickers.items() if '/USDT:USDT' in s and t['quoteVolume'] > 5000000]
            
            trade_found = False
            
            for symbol in active_symbols:
                if check_cooldown(symbol): continue
                    
                df_15m = await fetch_data(async_ex, symbol, '15m')
                if df_15m is None: continue
                
                score_15m, direction, rvol = calculate_math_score(df_15m)
                
                # The 15m Trigger (Must be >= 60 to call AI, AI makes it 75+)
                if score_15m >= 60 and rvol >= 2.5:
                    final_score = call_claude_ai(symbol, '15m', score_15m)
                    
                    if final_score >= 75:
                        # Deep MTF Confluence Check
                        if await check_mtf_confluence(async_ex, symbol, direction):
                            atr = calculate_atr(df_15m)
                            sl_price = get_structural_sl(df_15m, direction, atr)
                            current_price = df_15m['close'].iloc[-1]
                            
                            print(f"🔥 PERFECT SETUP: {symbol} | Dir: {direction} | RVOL: {rvol:.2f}x")
                            order, status = execute_atomic_trade(sync_ex, symbol, direction, current_price, sl_price)
                            
                            if order:
                                trade_found = True
                                await async_ex.close()
                                # Shift to Bodyguard (halts scanner)
                                bodyguard_monitor(sync_ex, symbol, direction, current_price, final_score, rvol)
                                break 
                            else:
                                log_ghost_trade(symbol, final_score, f"Skipped: {status}")
                        else:
                            log_ghost_trade(symbol, final_score, "Skipped: MTF Confluence Failed")
            
            if not trade_found:
                print("💤 No setups hit 75+. Waiting 60 seconds...")
                await asyncio.sleep(60)
            else:
                # Reconnect Async Exchange after Bodyguard completes a trade
                async_ex = ccxt_async.binance({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})
                
        except Exception as e:
            print(f"Scanner API Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
