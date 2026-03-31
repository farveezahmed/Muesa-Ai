import os
import asyncio
import ccxt.pro as ccxt
from flask import Flask
import threading

# --- DASHBOARD SETUP ---
app = Flask(__name__)
market_data = {}

@app.route('/')
def dashboard():
    html = "<h1>🚀 MUESA LIVE DASHBOARD</h1><hr>"
    html += f"<h3>📡 Tracking {len(market_data)} Live Symbols...</h3>"
    html += "<table border='1'><tr><th>Symbol</th><th>Price</th></tr>"
    # Show the first 20 coins found in the stream
    for sym, price in list(market_data.items())[:20]:
        # FIXED: Removed the extra colon after 'f'
        html += f"<tr><td>{sym}</td><td>{price}</td></tr>"
    html += "</table>"
    return html

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- THE PURE WEBSOCKET ENGINE ---
async def scan_market_live():
    global market_data
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    print("🚀 MUESA WEBSOCKET ENGINE: STEALTH MODE ONLINE")
    
    try:
        while True:
            tickers = await exchange.watch_tickers()
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT:USDT'):
                    market_data[symbol] = data['last']
            await asyncio.sleep(0.1) 
    except Exception as e:
        print(f"‼️ ENGINE ERROR: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(scan_market_live())
