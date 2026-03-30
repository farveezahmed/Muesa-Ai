import ccxt
import time
import os
from datetime import datetime
from muesa_logic import validate_trade_setup
from muesa_executor import MuesaExecutor

print("--- MUESA SYSTEM BOOT SEQUENCE INITIATED ---")

API_KEY = os.environ.get('BINANCE_API_KEY')
API_SECRET = os.environ.get('BINANCE_SECRET_KEY')

exchange = ccxt.binance({'apiKey': API_KEY, 'secret': API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'future'}})
muesa_trader = MuesaExecutor(api_key=API_KEY, api_secret=API_SECRET, testnet=False)

WATCHLIST = ["BTC/USDT", "ETH/USDT", "VANRY/USDT", "SOL/USDT"]
WALLET_BALANCE = 1000 

def scan_markets():
    print(f"\n[{datetime.now()}] Starting MUESA 15-Min Market Scan...")
    
    for symbol in WATCHLIST:
        try:
            current_price = exchange.fetch_ticker(symbol)['last']
            print(f"👀 Scanning {symbol} - Live Price: {current_price}")
            
            live_market_data = {
                "chart_formation_valid": False, "volume_3x_ma10": False, "strong_support_resistance": True,
                "funding_rate": 0.01, "open_interest_rising": True, "news_sentiment_positive": True,
                "spread_below_03": True, "price_at_key_fib": False, "rsi_bullish_divergence": False,
                "macd_crossover": False, "entry_price": current_price, "atr": current_price * 0.02, "trade_type": "LONG"
            }

            decision = validate_trade_setup(symbol, live_market_data, WALLET_BALANCE, active_trades_count=0)
            
            if decision["approved"]:
                print(f"🟢 75+ SCORE FOR {symbol}! EXECUTING...")
                # muesa_trader.execute_trade(decision) # SAFELY DISABLED FOR TESTING
            else:
                print(f"🔴 SKIP {symbol}: {decision['reason']}")

        except Exception as e:
            print(f"⚠️ Error scanning {symbol}: {e}")

if __name__ == "__main__":
    print("MUESA is LIVE.")
    while True:
        scan_markets()
        print("Scan complete. MUESA is resting for 15 minutes...")
        time.sleep(900)
