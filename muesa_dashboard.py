import os
import asyncio
import ccxt.pro as ccxt
from flask import Flask
import threading

# --- DASHBOARD SETUP ---
app = Flask(__name__)
top_scores = {}

@app.route('/')
def dashboard():
    html = "<h1>🚀 MUESA LIVE DASHBOARD</h1><hr>"
    html += "<h3>📡 Tracking Live Market...</h3>"
    html += "<table border='1'><tr><th>Symbol</th><th>Last Price</th><th>AI Score</th></tr>"
    for sym, data in sorted(top_scores.items(), key=lambda x: x[1]['score'], reverse=True)[:10]:
        html += f"<tr><td>{sym}</td><td>{data['price']}</td><td><b>{data['score']}</b></td></tr>"
    html += "</table>"
    return html

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# --- MUESA ENGINE ---
async def scan_market_live():
    global top_scores
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    print("🚀 MUESA WEBSOCKET + DASHBOARD ONLINE")
    
    try:
        while True:
            tickers = await exchange.watch_tickers()
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT:USDT'):
                    # Dummy AI Calculation for the Dashboard
                    score = (data['percentage'] + 5) * 10 
                    top_scores[symbol] = {'price': data['last'], 'score': round(score, 2)}
            await asyncio.sleep(1)
    except Exception as e:
        print(f"‼️ ERROR: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    # Start the Web Dashboard in a separate thread
    threading.Thread(target=run_flask, daemon=True).start()
    # Start the Websocket Scanner
    asyncio.run(scan_market_live())
