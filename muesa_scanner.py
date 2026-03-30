import ccxt
import time
import os
import pandas as pd
from datetime import datetime
from muesa_logic import validate_trade_setup
from muesa_executor import MuesaExecutor

print("--- MUESA SMART SCANNER BOOT SEQUENCE ---")

# 1. Connect to Binance
API_KEY = os.environ.get('BINANCE_API_KEY')
API_SECRET = os.environ.get('BINANCE_SECRET_KEY')

exchange = ccxt.binance({
    'apiKey': API_KEY, 'secret': API_SECRET, 
    'enableRateLimit': True, 'options': {'defaultType': 'future'}
})
muesa_trader = MuesaExecutor(api_key=API_KEY, api_secret=API_SECRET, testnet=False)

WATCHLIST = ["BTC/USDT", "ETH/USDT", "VANRY/USDT", "SOL/USDT"]
WALLET_BALANCE = 1000 

def get_live_indicators(symbol):
    """Downloads last 100 candles and calculates real technicals."""
    print(f"📊 Analyzing technicals for {symbol}...")
    bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Calculate RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1+rs))
    current_rsi = rsi.iloc[-1]

    # Calculate Volume MA10
    avg_volume = df['volume'].rolling(window=10).mean().iloc[-1]
    current_volume = df['volume'].iloc[-1]
    volume_spike = current_volume > (avg_volume * 3)

    # Calculate Moving Averages (EMA 9 and EMA 21)
    ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
    
    return {
        "rsi": current_rsi,
        "volume_spike": volume_spike,
        "ema_cross": ema9 > ema21,
        "current_price": df['close'].iloc[-1]
    }

def scan_markets():
    print(f"\n[{datetime.now()}] Starting MUESA 15-Min Smart Scan...")
    
    for symbol in WATCHLIST:
        try:
            tech = get_live_indicators(symbol)
            
            # Now we feed REAL data into the Brain
            live_market_data = {
                "chart_formation_valid": tech["ema_cross"], # Using EMA cross as a proxy for trend
                "volume_3x_ma10": tech["volume_spike"], 
                "strong_support_resistance": True, 
                "funding_rate": 0.01, 
                "open_interest_rising": True, 
                "news_sentiment_positive": True,
                "spread_below_03": True, 
                "price_at_key_fib": False, 
                "rsi_bullish_divergence": tech["rsi"] < 30, # Oversold condition
                "macd_crossover": tech["ema_cross"],
                "entry_price": tech["current_price"], 
                "atr": tech["current_price"] * 0.02, 
                "trade_type": "LONG"
            }

            decision = validate_trade_setup(symbol, live_market_data, WALLET_BALANCE, active_trades_count=0)
            
            print(f"🔍 {symbol} | Price: {tech['current_price']} | RSI: {tech['rsi']:.2f} | Vol Spike: {tech['volume_spike']}")

            if decision["approved"]:
                print(f"🟢 75+ SCORE DETECTED! (Score: {decision['score']})")
                # muesa_trader.execute_trade(decision) # STILL LOCKED FOR TESTING
            else:
                print(f"🔴 SKIP: {decision['reason']}")

        except Exception as e:
            print(f"⚠️ Error scanning {symbol}: {e}")

from threading import Thread
from flask import Flask

# This creates a tiny "Fake Website" so Railway stays awake
app = Flask(__name__)
@app.route('/')
def home(): return "MUESA IS WATCHFUL"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    # Start the "Keep-Alive" website in the background
    Thread(target=run_web).start()
    
    print("MUESA Smart Scanner is LIVE and Always Awake.")
    while True:
        scan_markets()
        print("Scan complete. MUESA is resting for 15 minutes...")
        for i in range(15):
            time.sleep(60)
            print(f"Heartbeat: MUESA is watchful... ({14-i} mins left)")
        for i in range(15):
            time.sleep(60)
            print(f"Heartbeat: MUESA is watchful... ({14-i} mins left)")
