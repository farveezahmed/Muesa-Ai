import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

async def scan_market():
    init_db()
    # Fixed for Binance Futures
    exchange = ccxt_async.binance({'apiKey': API_KEY, 'secret': SECRET_KEY, 'options': {'defaultType': 'future'}})
    print("🚀 MUESA SILENT HUNTER ONLINE | AGGRESSIVE MODE")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            # Aggressive $15M Volume Filter
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                
                score, side, rvol = calculate_math_score(df)
                
                if score >= 50 and rvol >= 1.5:
                    final_score = call_claude_ai(symbol, '15m', score)
                    
                    if final_score >= 65:
                        price = df['close'].iloc[-1]
                        sl, tp = get_aggressive_targets(df, side)
                        log_trade(symbol, side, price, sl, tp, final_score)
                        print(f"✅ {datetime.now().strftime('%H:%M:%S')} | {symbol} {side} | Score: {final_score}")
                    else:
                        log_ghost_trade(symbol, final_score, "AI Rejected")

            await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
