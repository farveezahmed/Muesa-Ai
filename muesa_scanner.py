import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd

# 1. MECHANICAL SYNC: Pull keys from Railway Variables
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

async def scan_market():
    # Initialize Binance Futures
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })

    print(f"🚀 MUESA FULL-MARKET HUNTER ONLINE")
    print(f"📡 DEBUG: Connecting with Key: {str(API_KEY)[:5]}...")

    try:
        while True:
            # Load all USDT Markets
            markets = await exchange.load_markets()
            symbols = [s for s in markets if s.endswith('/USDT')]
            
            print(f"🔎 New Scan Started: Checking {len(symbols)} coins...")

            for symbol in symbols:
                try:
                    # 2. THE GOVERNOR: Wait 1.5 seconds per coin to prevent "Teapot" ban
                    await asyncio.sleep(1.5) 
                    
                    # Fetch 15m Candles
                    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    last_price = df['close'].iloc[-1]
                    volume = df['volume'].iloc[-1]

                    # LOGIC: Check for your strategy (e.g., Volume Spike or RSI)
                    # If score > 65: call_claude_ai(symbol) and place_trade(symbol)
                    
                    print(f"✅ Checked {symbol} | Price: {last_price} | Vol: {volume:.2f}")

                except Exception as e:
                    if "418" in str(e):
                        print(f"⚠️ TEAPOT DETECTED! Increasing sleep to 5 seconds...")
                        await asyncio.sleep(5)
                    else:
                        print(f"❌ Error checking {symbol}: {e}")
                    continue

            print("💤 Full scan complete. Resting for 1 minute...")
            await asyncio.sleep(60)

    except Exception as e:
        print(f"‼️ CRITICAL ERROR: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    # Ensure Python shows logs immediately
    os.environ['PYTHONUNBUFFERED'] = '1'
    asyncio.run(scan_market())
