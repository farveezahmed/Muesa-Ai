import os
import asyncio
import ccxt.pro as ccxt  # Note: This is the Pro version for Websockets
import pandas as pd

# 1. MECHANICAL SYNC
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

async def scan_market_websocket():
    # Initialize Binance Futures Websocket
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': {'defaultType': 'future'},
    })

    print(f"🚀 MUESA WEBSOCKET ENGINE ONLINE")
    print(f"📡 NO MORE RATE LIMITS - LISTENING LIVE")

    try:
        # We listen to the "Ticker" stream for ALL coins at once
        while True:
            # This opens ONE connection and Binance pushes ALL prices to us
            tickers = await exchange.watch_tickers()
            
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT:USDT'): # Standard Futures format
                    last_price = data['last']
                    volume = data['quoteVolume'] # 24h Volume
                    
                    # Logic: If price or volume spikes, MUESA triggers
                    # Example: print(f"⚡ {symbol}: {last_price}")
                    
            # We only print a summary every 30 seconds so your logs stay clean
            print(f"✅ Live Stream Active: Tracking {len(tickers)} symbols...")
            await asyncio.sleep(30)

    except Exception as e:
        print(f"‼️ WEBSOCKET ERROR: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    os.environ['PYTHONUNBUFFERED'] = '1'
    asyncio.run(scan_market_websocket())
