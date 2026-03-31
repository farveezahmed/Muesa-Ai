import ccxt.async_support as ccxt_async
import asyncio
import pandas as pd
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade

# PASTE YOUR KEYS HERE
API_KEY = "YOUR_KEY"
SECRET_KEY = "YOUR_SECRET"

async def scan_market():
    init_db()
    exchange = ccxt_async.binance({
        'apiKey': API_KEY, 'secret': SECRET_KEY,
        'options': {'defaultType': 'future', 'adjustForTimeDifference': True},
        'enableRateLimit': True
    })

    print("🚀 MUESA FULL-MARKET HUNTER ONLINE")
    
    while True:
        try:
            # 1. Get every coin with volume > $15M
            tickers = await exchange.fetch_tickers()
            symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            print(f"🔎 New Scan Started: Checking {len(symbols)} coins...")

            for symbol in symbols:
                # 2. THE GOVERNOR: Wait 1.5 seconds so Binance doesn't ban us
                await asyncio.sleep(1.5) 
                
                try:
                    bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                    
                    score, side, rvol = calculate_math_score(df)
                    if score >= 50 and rvol >= 1.5:
                        final_score = call_claude_ai(symbol, '15m', score)
                        
                        if final_score >= 65:
                            # [TRADE EXECUTION CODE GOES HERE - Use $15/5x leverage]
                            print(f"🔥 OPPORTUNITY FOUND: {symbol} (Score: {final_score})")
                            
                except Exception:
                    continue 

            print("✅ Market Scan Complete. Resting for 2 minutes.")
            await asyncio.sleep(120) 
            
        except Exception as e:
            print(f"⚠️ Connection Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
