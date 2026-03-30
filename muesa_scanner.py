import ccxt, time, os, pandas as pd, requests
from datetime import datetime
from threading import Thread
from flask import Flask

# --- 1. Keep-Alive Web Server ---
app = Flask(__name__)
@app.route('/')
def home(): return "MUESA IS WATCHFUL"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    print(f"--- Web Server Starting on Port {port} ---")
    app.run(host="0.0.0.0", port=port)

# --- 2. Telegram Notification ---
def send_muesa_alert(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("⚠️ Telegram Keys Missing!")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
        print("📩 Telegram Message Sent Successfully!")
    except Exception as e:
        print(f"⚠️ Telegram Failed: {e}")

# --- 3. Advanced Indicators Logic ---
def get_live_indicators(exchange, symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Basic RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + (gain / loss)))
    
    # Pattern Calculations
    vol_spike = df['volume'].iloc[-1] > (df['volume'].rolling(10).mean().iloc[-1] * 3)
    ema9 = df['close'].ewm(span=9).mean().iloc[-1]
    ema21 = df['close'].ewm(span=21).mean().iloc[-1]
    
    # New Patterns Data
    price_change = ((df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1]) * 100
    support_level = df['low'].min()
    daily_change = ((df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]) * 100
    
    return {
        "rsi": rsi.iloc[-1], 
        "volume_spike": vol_spike, 
        "ema_cross": ema9 > ema21, 
        "current_price": df['close'].iloc[-1],
        "price_change": price_change,
        "support_level": support_level,
        "daily_change": daily_change
    }

# --- 4. The Brain (Scanning & Trading) ---
def scan_markets():
    API_KEY = os.environ.get('BINANCE_API_KEY')
    API_SECRET = os.environ.get('BINANCE_SECRET_KEY')
    exchange = ccxt.binance({
        'apiKey': API_KEY, 'secret': API_SECRET, 
        'enableRateLimit': True, 'options': {'defaultType': 'future'}
    })
    
    WATCHLIST = ["BTC/USDT", "ETH/USDT", "VANRY/USDT", "SOL/USDT"]
    print(f"\n[{datetime.now()}] 🔍 MUESA Scanning Watchlist...")
    
    for symbol in WATCHLIST:
        try:
            tech = get_live_indicators(exchange, symbol)
            print(f"📊 {symbol} | Price: {tech['current_price']} | RSI: {tech['rsi']:.2f}")
            
            # Use the Advanced Logic
            from muesa_logic import validate_trade_setup
            import muesa_trader
            
            decision = validate_trade_setup(symbol, tech)
            
            # Send Telegram for ANY score over 50 (Watching)
            if decision['score'] >= 50:
                status = "✅ APPROVED" if decision['approved'] else "👀 WATCHING"
                msg = f"🔍 *MUESA SCAN: {symbol}*\nStatus: {status}\nScore: {decision['score']}/100\nPrice: {tech['current_price']}\nPatterns: {decision['reason']}"
                send_muesa_alert(msg)
                
                # Execute if Score is 75+
                if decision["approved"]:
                    muesa_trader.execute_trade(decision)
                    
        except Exception as e:
            print(f"⚠️ Error scanning {symbol}: {e}")

# --- 5. Main Execution Loop ---
if __name__ == "__main__":
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    time.sleep(5)
    
    send_muesa_alert("🚀 *MUESA High-Performance System LIVE!*\nScoring Rule: 75+ Score Required for Trade.")
    
    while True:
        scan_markets()
        print("Scan complete. MUESA is resting for 15 minutes...")
        for i in range(15):
            time.sleep(60)
            print(f"Heartbeat: MUESA is watchful... ({14-i} mins left)")
