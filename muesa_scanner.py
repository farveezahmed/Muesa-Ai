import ccxt, time, os, pandas as pd, requests
from datetime import datetime
from threading import Thread
from flask import Flask

# --- 1. Keep-Alive Web Server (Starts First) ---
app = Flask(__name__)
@app.route('/')
def home(): return "MUESA IS WATCHFUL"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    print(f"--- Web Server Starting on Port {port} ---")
    app.run(host="0.0.0.0", port=port)

# --- 2. Telegram Notification with Error Logging ---
def send_muesa_alert(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("⚠️ Telegram Keys Missing in Variables!")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
        if response.status_code != 200:
            print(f"⚠️ Telegram Error: {response.text}")
        else:
            print("📩 Telegram Message Sent Successfully!")
    except Exception as e:
        print(f"⚠️ Telegram Connection Failed: {e}")

# --- 3. Indicators Logic ---
def get_live_indicators(exchange, symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # RSI Calculation
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # Volume Spike (3x average)
    vol_spike = df['volume'].iloc[-1] > (df['volume'].rolling(10).mean().iloc[-1] * 3)
    
    # EMA Cross (9 over 21)
    ema9 = df['close'].ewm(span=9).mean().iloc[-1]
    ema21 = df['close'].ewm(span=21).mean().iloc[-1]
    
    return {
        "rsi": rsi.iloc[-1], 
        "volume_spike": vol_spike, 
        "ema_cross": ema9 > ema21, 
        "current_price": df['close'].iloc[-1]
    }

# --- 4. The Brain (Scanning & Trading) ---
def scan_markets():
    API_KEY = os.environ.get('BINANCE_API_KEY')
    API_SECRET = os.environ.get('BINANCE_SECRET_KEY')
    exchange = ccxt.binance({
        'apiKey': API_KEY, 
        'secret': API_SECRET, 
        'enableRateLimit': True, 
        'options': {'defaultType': 'future'}
    })
    
    WATCHLIST = ["BTC/USDT", "ETH/USDT", "VANRY/USDT", "SOL/USDT"]
    print(f"\n[{datetime.now()}] 🔍 MUESA Scanning Watchlist...")
    
    for symbol in WATCHLIST:
        try:
            tech = get_live_indicators(exchange, symbol)
            print(f"📊 {symbol} | Price: {tech['current_price']} | RSI: {tech['rsi']:.2f}")
            
            # --- STEP 1: Telegram Alert for Oversold ---
            if tech['rsi'] < 30:
                send_muesa_alert(f"⚠️ *OVERSOLD ALERT:* {symbol}\nPrice: {tech['current_price']}\nRSI: {tech['rsi']:.2f}")

                # --- STEP 2: The Final Unlock (LIVE TRADING) ---
                from muesa_logic import validate_trade_setup
                import muesa_trader
                
                decision = validate_trade_setup(symbol, tech)
                if decision["approved"]:
                    print(f"✅ TRADE APPROVED for {symbol}! Executing...")
                    send_muesa_alert(f"✅ *TRADE APPROVED:* {symbol}\nExecuting order on Binance...")
                    muesa_trader.execute_trade(decision)
                else:
                    print(f"🔴 SKIP {symbol}: Score below 75.")
                    
        except Exception as e:
            print(f"⚠️ Error scanning {symbol}: {e}")

# --- 5. Main Execution Loop ---
if __name__ == "__main__":
    # Start Keep-Alive Web Server
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    
    # Wait for server to boot
    time.sleep(5)
    
    # Initial System Check
    send_muesa_alert("🚀 *MUESA Live Trading System Online!* Watching the markets 24/7.")
    
    while True:
        scan_markets()
        print("Scan complete. MUESA is resting for 15 minutes...")
        
        # 15-minute countdown with heartbeat logs
        for i in range(15):
            time.sleep(60)
            print(f"Heartbeat: MUESA is watchful... ({14-i} mins left)")
