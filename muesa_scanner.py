import os
import asyncio
import ccxt.pro as ccxt
from flask import Flask
import threading

# --- DASHBOARD SETUP ---
app = Flask(__name__)
# This stores the "Live Market" in your RAM (Safe from Binance Teapots)
market_data = {}

@app.route('/')
def dashboard():
    html = "<h1>🚀 MUESA LIVE DASHBOARD</h1><hr>"
    html += f"<h3>📡 Tracking {len(market_data)} Live Symbols...</h3>"
    html += "<table border='1'><tr><th>Symbol</th><th>Price</th></tr>"
    # This loop shows the top 20 moving coins on your dashboard
    for sym, price in list(market_data.items())[:20]:
        # FIXED: Removed the Syntax Error (The extra colon is gone!)
        html += f"<tr><td>{sym}</td><td>{price}</td></tr>"
    html += "</table>"
    return html

def run_flask():
    # Railway looks for Port 8080 by default
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- THE PURE WEBSOCKET LISTENER ---
async def scan_market_live():
    global market_data
    # We use Pro mode to "Listen" passively to the stream
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    print("🚀 MUESA WEBSOCKET ENGINE: STEALTH MODE ONLINE")
    
    try:
        while True:
            # Passive 'watch_tickers' stream (Binance PUSHES to us)
            tickers = await exchange.watch_tickers()
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT:USDT'):
                    # Save locally (Zero extra calls to Binance API)
                    market_data[symbol] = data['last']
            # Small CPU breather
            await asyncio.sleep(0.1) 
    except Exception as e:
        print(f"‼️ ENGINE ERROR: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    # 1. Start the Visual Dashboard
    threading.Thread(target=run_flask, daemon=True).start()
    # 2. Start the High-Speed Engine
    asyncio.run(scan_market_live())
